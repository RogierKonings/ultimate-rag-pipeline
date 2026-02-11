//! Retrieval Service - Rust HTTP Binary
//!
//! This is the main entry point for the Rust retrieval service that provides
//! hybrid search (semantic + keyword) with ACL filtering and reranking.
//!
//! # API Endpoints
//!
//! - `POST /api/v1/retrieve` - Single query retrieval
//! - `POST /api/v1/retrieve/multi` - Multi-query retrieval
//! - `GET /health` - Full health check with component status
//! - `GET /health/live` - Kubernetes liveness probe
//! - `GET /health/ready` - Kubernetes readiness probe
//! - `GET /metrics` - Prometheus metrics endpoint
//!
//! # Environment Variables
//!
//! See the `ServiceConfig::from_env()` documentation for all supported
//! environment variables.

use std::sync::Arc;

use tokio::signal;
use tracing::{error, info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

use rag_cache::{CacheClient, CacheConfig};
use rag_retrieval::acl::{ACLFilter, ACLFilterConfig};
use rag_retrieval::api::{run_server_with_config, AppState, ServerConfig};
use rag_retrieval::cache::RetrievalCache;
use rag_retrieval::embedding::{EmbeddingClient, EmbeddingConfig};
use rag_retrieval::hybrid::{HybridSearchConfig, HybridSearcher};
use rag_retrieval::query::{
    HydeConfig, HydeGenerator, QueryCacheConfig, QueryExpander, QueryExpanderConfig,
};
use rag_retrieval::reranking::{RerankerConfig, RerankerService};
use rag_retrieval::search::{
    KeywordSearchConfig, KeywordSearcher, SemanticSearchConfig, SemanticSearcher,
};

#[tokio::main]
async fn main() {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| {
                "retrieval_service=info,rag_retrieval=info,tower_http=info".into()
            }),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    info!(
        "Starting Rust Retrieval Service v{}",
        env!("CARGO_PKG_VERSION")
    );

    // Load configuration from environment
    let server_config = ServerConfig::from_env();
    info!(addr = %server_config.addr, "Server configuration loaded");

    // Initialize components
    let state = match initialize_app_state().await {
        Ok(state) => Arc::new(state),
        Err(e) => {
            error!("Failed to initialize application: {}", e);
            std::process::exit(1);
        }
    };

    info!("All components initialized successfully");

    // Run server with graceful shutdown
    let shutdown_signal = async {
        let ctrl_c = async {
            signal::ctrl_c()
                .await
                .expect("Failed to install Ctrl+C handler");
        };

        #[cfg(unix)]
        let terminate = async {
            signal::unix::signal(signal::unix::SignalKind::terminate())
                .expect("Failed to install SIGTERM handler")
                .recv()
                .await;
        };

        #[cfg(not(unix))]
        let terminate = std::future::pending::<()>();

        tokio::select! {
            () = ctrl_c => info!("Received Ctrl+C, shutting down"),
            () = terminate => info!("Received SIGTERM, shutting down"),
        }
    };

    if let Err(e) = run_server_with_config(state, &server_config, shutdown_signal).await {
        error!("Server error: {}", e);
        std::process::exit(1);
    }

    info!("Server shut down successfully");
}

/// Initialize all application components using environment-based configuration.
#[allow(clippy::too_many_lines)]
async fn initialize_app_state() -> Result<AppState, Box<dyn std::error::Error + Send + Sync>> {
    // Load configs from environment
    let semantic_config = SemanticSearchConfig::from_env();
    let keyword_config = KeywordSearchConfig::from_env();
    let embedding_config = EmbeddingConfig::from_env();
    let reranker_config = RerankerConfig::from_env();
    let hybrid_config = HybridSearchConfig::from_env();
    let acl_config = ACLFilterConfig::from_env();

    // Initialize semantic searcher (Qdrant)
    info!(
        url = %semantic_config.url,
        collection = %semantic_config.collection,
        "Connecting to Qdrant"
    );
    let semantic = SemanticSearcher::new(&semantic_config).await?;
    info!("Connected to Qdrant");

    // Initialize keyword searcher (OpenSearch)
    info!(
        url = %keyword_config.url,
        index = %keyword_config.index,
        "Connecting to OpenSearch"
    );
    let keyword = KeywordSearcher::new(&keyword_config)?;
    info!("Connected to OpenSearch");

    // Initialize embedding client
    info!(
        url = %embedding_config.url,
        model = %embedding_config.model,
        "Configuring embedding client"
    );
    let embedding = EmbeddingClient::new(embedding_config)?;

    // Initialize reranker
    let reranker = if std::env::var("RERANKER_ENABLED")
        .map(|v| v.to_lowercase() == "true")
        .unwrap_or(true)
    {
        info!(
            url = %reranker_config.gateway_url,
            model = %reranker_config.model,
            "Configuring reranker"
        );
        match RerankerService::new(reranker_config) {
            Ok(service) => Some(Arc::new(service)),
            Err(e) => {
                warn!(
                    "Failed to initialize reranker, continuing without it: {}",
                    e
                );
                None
            }
        }
    } else {
        warn!("Reranker disabled via RERANKER_ENABLED=false");
        None
    };

    // Initialize query expander (optional)
    let query_expander = {
        let config = QueryExpanderConfig::from_env();
        if config.enabled {
            info!(
                max_expansions = config.max_expansions,
                use_synonyms = config.use_synonyms,
                use_llm = config.use_llm,
                "Configuring query expander"
            );
            match QueryExpander::new(config) {
                Ok(expander) => Some(Arc::new(expander)),
                Err(e) => {
                    warn!(
                        "Failed to initialize query expander, continuing without it: {}",
                        e
                    );
                    None
                }
            }
        } else {
            warn!("Query expansion disabled via EXPANSION_ENABLED=false");
            None
        }
    };

    // Initialize HyDE generator (optional)
    let hyde_generator = {
        let config = HydeConfig::from_env();
        if config.enabled {
            info!(
                model = %config.model,
                num_docs = config.num_hypothetical_docs,
                timeout_ms = config.timeout_ms,
                "Configuring HyDE generator"
            );
            match HydeGenerator::new(config) {
                Ok(generator) => Some(Arc::new(generator)),
                Err(e) => {
                    warn!(
                        "Failed to initialize HyDE generator, continuing without it: {}",
                        e
                    );
                    None
                }
            }
        } else {
            warn!("HyDE disabled via HYDE_ENABLED=false");
            None
        }
    };

    // Initialize hybrid searcher
    info!(
        semantic_weight = hybrid_config.semantic_weight,
        keyword_weight = hybrid_config.keyword_weight,
        "Creating hybrid searcher"
    );
    let hybrid = HybridSearcher::new(Arc::new(semantic), Arc::new(keyword), hybrid_config);

    // Initialize ACL filter
    let acl_filter = ACLFilter::new(acl_config);

    // Initialize retrieval cache (optional, opt-in)
    let retrieval_cache = {
        let cache_url =
            std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://localhost:6379".to_string());
        let cache_enabled = std::env::var("RETRIEVAL_CACHE_ENABLED")
            .map(|v| v.to_lowercase() == "true")
            .unwrap_or(false);

        if cache_enabled {
            info!("Initializing retrieval cache");
            let cache_config = CacheConfig {
                url: cache_url,
                ..CacheConfig::default()
            };
            match CacheClient::connect(&cache_config).await {
                Ok(client) => {
                    let query_cache_config = QueryCacheConfig::default();
                    Some(Arc::new(RetrievalCache::new(
                        query_cache_config,
                        Arc::new(client),
                    )))
                }
                Err(e) => {
                    warn!(
                        "Failed to initialize retrieval cache, continuing without it: {}",
                        e
                    );
                    None
                }
            }
        } else {
            info!("Retrieval cache disabled (set RETRIEVAL_CACHE_ENABLED=true to enable)");
            None
        }
    };

    // Build application state
    let mut builder = AppState::builder()
        .hybrid(Arc::new(hybrid))
        .embedding(Arc::new(embedding))
        .acl_filter(Arc::new(acl_filter))
        .version(env!("CARGO_PKG_VERSION"));

    if let Some(reranker) = reranker {
        builder = builder.reranker(reranker);
    }
    if let Some(query_expander) = query_expander {
        builder = builder.query_expander(query_expander);
    }
    if let Some(hyde_generator) = hyde_generator {
        builder = builder.hyde_generator(hyde_generator);
    }
    if let Some(retrieval_cache) = retrieval_cache {
        builder = builder.retrieval_cache(retrieval_cache);
    }

    let state = builder.build()?;

    Ok(state)
}
