# Frontend Video RAG Design

> **Date:** 2026-01-20
> **Status:** Ready for implementation

## Overview

Add video upload, search, and playback capabilities to the frontend application. Users can upload videos, search across video content (transcripts, scene descriptions, OCR text), view timeline-based results, and play relevant clips.

## Navigation & Layout

### Tab-Based Navigation
- Top tabs in main content area: **Documents** | **Videos**
- URL reflects active tab (`/` for documents, `/?tab=videos` for videos)
- Search state preserved per tab when switching

### Videos Tab Layout
- **Sidebar (left)**: Video list with thumbnails and processing status
- **Main content (center-left, 60%)**: Search bar and timeline results
- **Player panel (right, 40%)**: Video player with clip context, collapsible

### Responsive Behavior
- On smaller screens, player panel becomes a modal overlay
- Tab bar remains visible at all breakpoints

## Video Sidebar

### Video List Item
- Thumbnail (~60x40px) or placeholder while processing
- Title (truncated)
- Duration (e.g., "2:34")
- Status indicator:
  - Processing: spinner + stage name ("Transcribing...", "Analyzing...", "Indexing...")
  - Ready: green checkmark
  - Failed: red icon + "Failed" with error tooltip

### Sections
- **Processing**: Videos currently being processed with progress
- **Your Videos**: Ready videos, sorted by upload date (newest first)

### Actions
- Click to select (loads in player panel)
- Hover shows delete button with confirmation

### Empty State
- "No videos yet" with upload prompt

## Video Upload

### Trigger
- Same "Upload" button in header
- Modal content adapts based on active tab

### Modal Content
- Large drag-and-drop zone with dashed border
- Accepted formats: MP4, MOV, AVI, MKV, WebM
- Limits displayed: max 5GB, 10 seconds - 60 minutes

### Queued Files Display
- Filename, file size, validation status
- Invalid files show inline error
- Remove button per file
- "Upload X videos" confirmation button

### Processing Flow
1. Modal closes on upload start
2. Videos appear in sidebar Processing section
3. Progress through stages: "Uploading..." → "Extracting audio..." → "Transcribing..." → "Analyzing scenes..." → "Indexing..."
4. On completion: moves to Your Videos, toast notification

## Video Search

### Search Bar
- Same style as document search
- Placeholder: "Search within your videos..."
- Example queries in empty state

### Result Card Structure
- Header: thumbnail, title, duration, match count badge
- Timeline strip below header
- Top 3 matches listed with timestamps and snippets
- "Show all X matches" expander

### Timeline Strip
- Horizontal bar representing full video duration
- Time labels at start and end
- Match markers as vertical lines/dots
- Marker intensity reflects relevance score
- Hover: tooltip with timestamp + snippet
- Click: loads clip in player panel

### Sorting
- Videos ordered by highest relevance score
- Videos with more high-scoring matches rank higher

## Video Player Panel

### Empty State
- Placeholder: "Select a video or click a timeline marker to preview"
- Collapsed or minimal width

### Loaded State
- HTML5 video player with standard controls
- Loads clip segment with 2-second padding
- Current timestamp overlay

### Segment Info (below player)
- Video title and total duration
- Segment timestamp range
- Relevance score badge

### Content Tabs
- **Transcript**: Speech text with matched terms highlighted
- **Scene**: Visual description from vision analysis
- **OCR**: On-screen text detected

### Navigation
- Previous/Next match arrows
- "Open full video" link

### Controls
- Collapse/expand chevron

## Error Handling

### Upload Errors
- Validation failure: inline error in modal
- Network error: retry button on sidebar item
- Processing failure: "Failed" status with error tooltip, retry/delete options

### Search Errors
- API failure: error banner with retry
- No results: friendly message
- Timeout: retry prompt

### Player Errors
- Clip generation fails: message with retry
- Stream unavailable: fallback message

### Status Polling
- Poll every 3 seconds while processing
- Max 30 minutes, then manual refresh option

### Network Issues
- Cached video list when offline
- Clear error for search without network

### Permission Errors
- 403: "Access denied" message
- 404: remove from local state

## File Structure

### API Layer (`frontend/src/lib/api/`)
```
video.ts          # CRUD: listVideos, getVideo, deleteVideo, uploadVideo, getVideoStatus
videoRetrieval.ts # Search: searchVideos
types.ts          # Add Video, VideoChunk, VideoSearchResult, VideoMatch
```

### Stores (`frontend/src/lib/stores/`)
```
videos.ts       # Video list, processing status, selection
videoSearch.ts  # Search query, results, loading
videoPlayer.ts  # Selected clip, playback state
```

### Components (`frontend/src/lib/components/`)
```
ContentTabs.svelte      # Documents/Videos tab switcher
VideoSidebar.svelte     # Video list with processing indicators
VideoUploadModal.svelte # Drag-drop upload
VideoSearchBar.svelte   # Search input
VideoResultCard.svelte  # Result with timeline
TimelineStrip.svelte    # Timeline with match markers
VideoPlayerPanel.svelte # Player with content tabs
VideoItem.svelte        # Sidebar list item
```

### Updated Files
```
+page.svelte    # Tab state, conditional rendering
+layout.svelte  # Header adjustments for upload context
```

### New Proxy Routes
```
frontend/src/routes/api/proxy/retrieval/[...path]/+server.ts
```

## Backend APIs Used

### Ingestion Service (port 8001)
- `GET /api/v1/videos` - List videos
- `POST /api/v1/videos/upload` - Upload video
- `GET /api/v1/videos/{id}/status` - Processing status
- `GET /api/v1/videos/{id}` - Video details
- `DELETE /api/v1/videos/{id}` - Delete with cascade

### Retrieval Service (port 8002)
- `POST /api/v1/retrieve/video` - Hybrid search
- `GET /api/v1/videos/{id}/clip` - Generate clip
- `GET /api/v1/videos/{id}/stream` - Full video stream
