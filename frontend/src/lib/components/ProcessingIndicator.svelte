<script lang="ts">
	import { Loader2, CheckCircle, XCircle, X } from 'lucide-svelte';
	import type { UploadJob } from '$lib/stores/upload';
	import { upload } from '$lib/stores/upload';

	interface Props {
		job: UploadJob;
	}

	let { job }: Props = $props();

	const StatusIcon = $derived.by(() => {
		switch (job.status) {
			case 'completed':
				return CheckCircle;
			case 'failed':
				return XCircle;
			default:
				return Loader2;
		}
	});

	const statusColor = $derived.by(() => {
		switch (job.status) {
			case 'completed':
				return 'text-[var(--color-success)]';
			case 'failed':
				return 'text-[var(--color-error)]';
			default:
				return 'text-[var(--color-accent)]';
		}
	});

	const progressBarColor = $derived.by(() => {
		switch (job.status) {
			case 'completed':
				return 'bg-[var(--color-success)]';
			case 'failed':
				return 'bg-[var(--color-error)]';
			default:
				return 'bg-[var(--color-accent)]';
		}
	});

	const isSpinning = $derived(job.status === 'uploading' || job.status === 'processing');
</script>

<div class="rounded-lg border border-[var(--color-border)] bg-gray-50 p-3">
	<div class="flex items-start justify-between gap-2">
		<div class="flex items-center gap-2 min-w-0">
			<div class={statusColor}>
				<StatusIcon class={`h-4 w-4 ${isSpinning ? 'animate-spin' : ''}`} />
			</div>
			<span class="truncate text-sm font-medium text-[var(--color-text-primary)]">
				{job.filename}
			</span>
		</div>

		{#if job.status === 'completed' || job.status === 'failed'}
			<button
				onclick={() => upload.removeJob(job.id)}
				class="shrink-0 rounded p-1 text-[var(--color-text-secondary)] hover:bg-gray-200 hover:text-[var(--color-text-primary)]"
			>
				<X class="h-3 w-3" />
			</button>
		{/if}
	</div>

	<!-- Progress Bar -->
	{#if job.status === 'uploading' || job.status === 'processing'}
		<div class="mt-2">
			<div class="score-bar">
				<div
					class={`score-bar-fill ${progressBarColor}`}
					style="width: {job.progress}%"
				></div>
			</div>
			<p class="mt-1 text-xs text-[var(--color-text-secondary)]">
				{job.status === 'uploading' ? 'Uploading...' : 'Processing...'} {job.progress}%
			</p>
		</div>
	{/if}

	<!-- Error Message -->
	{#if job.error}
		<p class="mt-2 text-xs text-[var(--color-error)]">{job.error}</p>
	{/if}
</div>
