<script lang="ts">
	import { getContext, onMount, tick } from 'svelte';

	import { formatFileSize, getLineCount } from '$lib/utils';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { settings } from '$lib/stores';
	import { getFileById } from '$lib/apis/files';

	import CodeBlock from '$lib/components/chat/Messages/CodeBlock.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';

	const i18n = getContext('i18n');

	const CONTENT_PREVIEW_LIMIT = 10000;
	let expandedContent = false;

	import Modal from './Modal.svelte';
	import XMark from '../icons/XMark.svelte';
	import Tooltip from './Tooltip.svelte';
	import Spinner from './Spinner.svelte';
	import PanzoomContainer from './PanzoomContainer.svelte';
	import Reset from '../icons/Reset.svelte';

	export let item;
	export let show = false;
	export let edit = false;

	let loading = false;

	let isImage = false;
	let selectedTab = '';

	let panzoomRef: PanzoomContainer;
	const resetImageView = () => {
		panzoomRef?.reset();
	};

	$: isMarkdown =
		item?.meta?.content_type === 'text/markdown' ||
		(item?.name && item?.name.toLowerCase().endsWith('.md'));

	$: isCode =
		item?.name &&
		(item.name.toLowerCase().endsWith('.py') ||
			item.name.toLowerCase().endsWith('.js') ||
			item.name.toLowerCase().endsWith('.ts') ||
			item.name.toLowerCase().endsWith('.java') ||
			item.name.toLowerCase().endsWith('.html') ||
			item.name.toLowerCase().endsWith('.css') ||
			item.name.toLowerCase().endsWith('.json') ||
			item.name.toLowerCase().endsWith('.cpp') ||
			item.name.toLowerCase().endsWith('.c') ||
			item.name.toLowerCase().endsWith('.h') ||
			item.name.toLowerCase().endsWith('.sh') ||
			item.name.toLowerCase().endsWith('.bash') ||
			item.name.toLowerCase().endsWith('.yaml') ||
			item.name.toLowerCase().endsWith('.yml') ||
			item.name.toLowerCase().endsWith('.xml') ||
			item.name.toLowerCase().endsWith('.sql') ||
			item.name.toLowerCase().endsWith('.go') ||
			item.name.toLowerCase().endsWith('.rs') ||
			item.name.toLowerCase().endsWith('.php') ||
			item.name.toLowerCase().endsWith('.rb'));

	$: isImage =
		(item?.meta?.content_type ?? '').startsWith('image/') ||
		(item?.name &&
			(item.name.toLowerCase().endsWith('.png') ||
				item.name.toLowerCase().endsWith('.jpg') ||
				item.name.toLowerCase().endsWith('.jpeg') ||
				item.name.toLowerCase().endsWith('.gif') ||
				item.name.toLowerCase().endsWith('.webp') ||
				item.name.toLowerCase().endsWith('.svg') ||
				item.name.toLowerCase().endsWith('.bmp') ||
				item.name.toLowerCase().endsWith('.ico')));

	const loadContent = async () => {
		selectedTab = '';
		expandedContent = false;
		if (item?.type === 'file') {
			loading = true;

			const file = await getFileById(localStorage.token, item.id).catch((e) => {
				console.error('Error fetching file:', e);
				return null;
			});

			if (file) {
				item.file = file || {};
			}

			loading = false;
		}

		await tick();
	};

	$: if (show) {
		loadContent();
	}

	onMount(() => {
		console.log(item);
	});
</script>

<Modal bind:show size="lg">
	<div class=" px-4.5 py-3.5 w-full flex flex-col justify-center dark:text-gray-400">
		<div class=" pb-2">
			<div class="flex items-start justify-between">
				<div>
					<div class=" font-normal text-lg dark:text-gray-100">
						<a
							href="#"
							class="hover:underline line-clamp-1"
							on:click|preventDefault={() => {
								if (item.type === 'file' || item.url) {
									let fileId = item?.id ?? item?.tempId;
									window.open(
										item.type === 'file'
											? item?.url?.startsWith('http')
												? item.url
												: `${WEBUI_API_BASE_URL}/files/${fileId}/content`
											: item.url,
										'_blank'
									);
								}
							}}
						>
							{item?.name ?? 'File'}
						</a>
					</div>
				</div>

				<div>
					<button
						on:click={() => {
							show = false;
						}}
					>
						<XMark />
					</button>
				</div>
			</div>

			<div>
				<div class="flex flex-col items-center md:flex-row gap-1 justify-between w-full">
					<div class=" flex flex-wrap text-xs gap-1 text-gray-500">
						{#if item.size}
							<div class="capitalize shrink-0">{formatFileSize(item.size)}</div>
							•
						{/if}

						{#if item?.file?.data?.content}
							<div class="capitalize shrink-0">
								{$i18n.t('{{COUNT}} extracted lines', {
									COUNT: getLineCount(item?.file?.data?.content ?? '')
								})}
							</div>

							<div class="flex items-center gap-1 shrink-0">
								• {$i18n.t('Formatting may be inconsistent from source.')}
							</div>
						{/if}
					</div>
				</div>
			</div>
		</div>

		<div class="max-h-[75vh] overflow-auto">
			{#if !loading}
				{#if isCode || isMarkdown}
					<div
						class="flex mb-2.5 scrollbar-none overflow-x-auto w-full border-b border-gray-50 dark:border-gray-850/30 text-center text-sm font-normal bg-transparent dark:text-gray-200"
					>
						<button
							class="min-w-fit py-1.5 px-4 border-b {selectedTab === ''
								? ' '
								: ' border-transparent text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition"
							type="button"
							on:click={() => {
								selectedTab = '';
							}}>{$i18n.t('Content')}</button
						>

						<button
							class="min-w-fit py-1.5 px-4 border-b {selectedTab === 'preview'
								? ' '
								: ' border-transparent text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition"
							type="button"
							on:click={() => {
								selectedTab = 'preview';
							}}>{$i18n.t('Preview')}</button
						>
					</div>
				{/if}

				{#if isImage}
					<div class="relative w-full max-h-[70vh] overflow-hidden">
						<div class="absolute top-2 right-2 z-10">
							<Tooltip content={$i18n.t('Reset view')}>
								<button
									class="p-1.5 rounded-lg bg-white/80 dark:bg-gray-850/80 backdrop-blur-sm shadow-sm hover:bg-gray-100 dark:hover:bg-gray-800 transition text-gray-500 dark:text-gray-400"
									on:click={resetImageView}
								>
									<Reset className="size-4" />
								</button>
							</Tooltip>
						</div>
						<PanzoomContainer bind:this={panzoomRef}>
							<img
								src={`${WEBUI_API_BASE_URL}/files/${item.id}/content`}
								alt={item?.name ?? 'Image'}
								class="w-full object-contain rounded-lg"
								loading="lazy"
								draggable="false"
							/>
						</PanzoomContainer>
					</div>
				{:else if selectedTab === ''}
					{#if item?.file?.data}
						{@const rawContent = (item?.file?.data?.content ?? '').trim() || 'No content'}
						{@const isTruncated =
							($settings?.renderMarkdownInPreviews ?? true) &&
							rawContent.length > CONTENT_PREVIEW_LIMIT &&
							!expandedContent}
						{#if $settings?.renderMarkdownInPreviews ?? true}
							<div
								class="max-h-96 overflow-scroll scrollbar-hidden text-sm prose dark:prose-invert max-w-full"
							>
								<Markdown
									content={isTruncated ? rawContent.slice(0, CONTENT_PREVIEW_LIMIT) : rawContent}
									id="file-preview"
								/>
							</div>
							{#if isTruncated}
								<button
									class="mt-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
									on:click={() => {
										expandedContent = true;
									}}
								>
									{$i18n.t('Show all ({{COUNT}} characters)', {
										COUNT: rawContent.length.toLocaleString()
									})}
								</button>
							{/if}
						{:else}
							<div class="max-h-96 overflow-scroll scrollbar-hidden text-xs whitespace-pre-wrap">
								{rawContent}
							</div>
						{/if}
					{:else if item?.content}
						{@const rawContent = (item?.content ?? '').trim() || 'No content'}
						{@const isTruncated =
							($settings?.renderMarkdownInPreviews ?? true) &&
							rawContent.length > CONTENT_PREVIEW_LIMIT &&
							!expandedContent}
						{#if $settings?.renderMarkdownInPreviews ?? true}
							<div
								class="max-h-96 overflow-scroll scrollbar-hidden text-sm prose dark:prose-invert max-w-full"
							>
								<Markdown
									content={isTruncated ? rawContent.slice(0, CONTENT_PREVIEW_LIMIT) : rawContent}
									id="file-preview-content"
								/>
							</div>
							{#if isTruncated}
								<button
									class="mt-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
									on:click={() => {
										expandedContent = true;
									}}
								>
									{$i18n.t('Show all ({{COUNT}} characters)', {
										COUNT: rawContent.length.toLocaleString()
									})}
								</button>
							{/if}
						{:else}
							<div class="max-h-96 overflow-scroll scrollbar-hidden text-xs whitespace-pre-wrap">
								{rawContent}
							</div>
						{/if}
					{:else}
						<div class="text-gray-500 text-sm p-4">{$i18n.t('No content')}</div>
					{/if}
				{:else if selectedTab === 'preview'}
					{#if isCode}
						<div class="max-h-[60vh] overflow-scroll scrollbar-hidden text-sm relative">
							<CodeBlock
								code={item.file.data.content}
								lang={item.name.split('.').pop()}
								token={null}
								edit={false}
								run={false}
								save={false}
							/>
						</div>
					{:else if isMarkdown}
						<div
							class="max-h-[60vh] overflow-scroll scrollbar-hidden text-sm prose dark:prose-invert max-w-full"
						>
							<Markdown content={item.file.data.content} id="markdown-viewer" />
						</div>
					{:else}
						<div class="max-h-96 overflow-scroll scrollbar-hidden text-xs whitespace-pre-wrap">
							{(item?.file?.data?.content ?? '').trim() || 'No content'}
						</div>
					{/if}
				{/if}
			{:else}
				<div class="flex items-center justify-center py-6">
					<Spinner className="size-5" />
				</div>
			{/if}
		</div>
	</div>
</Modal>
