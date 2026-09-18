<script lang="ts">
	import { getContext, onDestroy, tick } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';

	import { basicSetup, EditorView } from 'codemirror';
	import { keymap } from '@codemirror/view';
	import { Compartment, EditorState } from '@codemirror/state';
	import { json } from '@codemirror/lang-json';
	import { indentWithTab } from '@codemirror/commands';
	import { indentUnit } from '@codemirror/language';
	import { oneDark } from '@codemirror/theme-one-dark';

	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');

	export let output: any[] = [];
	export let onChange: (output: any[]) => void = () => {};

	let viewMode: 'visual' | 'json' = 'visual';
	let jsonError = '';

	// --- CodeMirror ---
	let cmContainer: HTMLDivElement;
	let cmEditor: EditorView | null = null;
	let editorTheme = new Compartment();

	function initCodeMirror() {
		if (cmEditor || !cmContainer) return;
		const isDark = document.documentElement.classList.contains('dark');
		cmEditor = new EditorView({
			state: EditorState.create({
				doc: JSON.stringify(output, null, 2),
				extensions: [
					basicSetup,
					keymap.of([indentWithTab]),
					indentUnit.of('  '),
					json(),
					editorTheme.of(isDark ? oneDark : []),
					EditorView.theme({
						'&': { fontSize: '13px' },
						'.cm-content': { fontFamily: 'ui-monospace, monospace' },
						'.cm-scroller': { maxHeight: '320px', overflow: 'auto' },
						'&.cm-focused': { outline: 'none' }
					}),
					EditorView.updateListener.of((e) => {
						if (e.docChanged) {
							try {
								const parsed = JSON.parse(e.state.doc.toString());
								if (Array.isArray(parsed)) {
									jsonError = '';
									output = parsed;
									onChange(output);
								} else {
									jsonError = 'Must be a JSON array';
								}
							} catch {
								jsonError = 'Invalid JSON';
							}
						}
					})
				]
			}),
			parent: cmContainer
		});
	}

	function destroyCodeMirror() {
		if (cmEditor) {
			cmEditor.destroy();
			cmEditor = null;
		}
	}

	async function switchToJson() {
		viewMode = 'json';
		await tick();
		initCodeMirror();
	}

	function switchToVisual() {
		if (jsonError) return;
		destroyCodeMirror();
		viewMode = 'visual';
	}

	onDestroy(() => destroyCodeMirror());

	// --- Display items ---

	interface DisplayItem {
		type: 'message' | 'reasoning';
		indices: number[];
		item: any;
	}

	function buildDisplayItems(items: any[]): DisplayItem[] {
		const result: DisplayItem[] = [];

		for (let i = 0; i < items.length; i++) {
			const item = items[i];
			const t = item?.type ?? '';
			if (t === 'message') {
				result.push({ type: 'message', indices: [i], item });
			} else if (t === 'reasoning') {
				result.push({ type: 'reasoning', indices: [i], item });
			}
		}
		return result;
	}

	$: displayItems = buildDisplayItems(output);

	// --- Helpers ---

	function getMessageText(item: any): string {
		return (item.content ?? [])
			.filter((p: any) => p && (p.type === 'output_text' || 'text' in p))
			.map((p: any) => p.text ?? '')
			.join('\n');
	}

	function updateMessageText(idx: number, text: string) {
		const next = [...output];
		const item = { ...next[idx] };
		const parts = (item.content ?? []).filter(
			(p: any) => p && (p.type === 'output_text' || 'text' in p)
		);
		item.content = [{ ...(parts[0] ?? { type: 'output_text' }), text }];
		next[idx] = item;
		output = next;
		onChange(output);
	}

	function getReasoningText(item: any): string {
		return (item.summary ?? item.content ?? [])
			.filter((p: any) => p && 'text' in p)
			.map((p: any) => p.text ?? '')
			.join('');
	}

	function updateReasoningText(idx: number, text: string) {
		const next = [...output];
		const item = { ...next[idx] };
		const key = item.summary ? 'summary' : 'content';
		item[key] = [{ type: 'text', text }];
		next[idx] = item;
		output = next;
		onChange(output);
	}

	function deleteIndices(indices: number[]) {
		const rm = new Set(indices);
		output = output.filter((_, i) => !rm.has(i));
		onChange(output);
	}

	function resizeEl(el: HTMLTextAreaElement) {
		const c = document.getElementById('messages-container');
		const s = c?.scrollTop;
		el.style.height = '';
		el.style.height = `${el.scrollHeight}px`;
		if (c && s !== undefined) c.scrollTop = s;
	}

	function autoResize(e: Event) {
		resizeEl(e.target as HTMLTextAreaElement);
	}

	/** Svelte action: auto-expand textarea to fit content on mount */
	function fitContent(el: HTMLTextAreaElement) {
		resizeEl(el);
	}

	function getItemLabel(di: DisplayItem): string {
		return di.type === 'message' ? 'Text' : 'Thought';
	}
</script>

<div class="w-full relative">
	<!-- Mode toggle -->
	<div class="absolute -top-0.5 right-0.5 z-10">
		<Tooltip
			content={viewMode === 'visual'
				? $i18n.t('Switch to JSON editor')
				: $i18n.t('Switch to visual editor')}
		>
			<button
				class="text-xs px-2 py-0.5 rounded-full transition-all text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200/50 dark:hover:bg-gray-700/50"
				on:click={() => (viewMode === 'visual' ? switchToJson() : switchToVisual())}
			>
				{viewMode === 'visual' ? $i18n.t('Visual') : 'JSON'}
			</button>
		</Tooltip>
	</div>

	{#if viewMode === 'json'}
		<div
			bind:this={cmContainer}
			class="w-full rounded-2xl overflow-hidden border border-gray-100 dark:border-gray-800"
		/>
		{#if jsonError}
			<div class="text-xs text-red-500 mt-1.5 px-1">{jsonError}</div>
		{/if}
	{:else}
		<!-- Visual editor: playground-style rows -->
		<div class="space-y-2 p-2 pt-3">
			{#each displayItems as di, idx}
				<div class="flex gap-2 group">
					<!-- Role label -->
					<div class="flex items-start pt-1.5">
						<div
							class="text-[0.6875rem] font-normal uppercase tracking-wide min-w-[4.5rem] text-gray-400 dark:text-gray-500"
						>
							{getItemLabel(di)}
						</div>
					</div>

					<!-- Content -->
					<div class="flex-1 min-w-0">
						{#if di.type === 'message'}
							<textarea
								use:fitContent
								class="w-full bg-transparent outline-hidden focus-visible:outline-none! resize-none overflow-hidden text-[0.9375rem] p-1.5 rounded-lg"
								value={getMessageText(di.item)}
								on:input={(e) => {
									updateMessageText(di.indices[0], e.target.value);
									autoResize(e);
								}}
								placeholder={$i18n.t('Message text...')}
								rows="1"
							/>
						{:else if di.type === 'reasoning'}
							<textarea
								use:fitContent
								class="w-full bg-transparent outline-hidden focus-visible:outline-none! resize-none overflow-hidden text-[0.9375rem] text-gray-500 dark:text-gray-400 p-1.5 rounded-lg"
								value={getReasoningText(di.item)}
								on:input={(e) => {
									updateReasoningText(di.indices[0], e.target.value);
									autoResize(e);
								}}
								placeholder={$i18n.t('Reasoning text...')}
								rows="1"
							/>
						{/if}
					</div>

					<!-- Delete -->
					<div class="pt-1.5">
						<button
							class="hover-reveal p-1 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition rounded-lg"
							aria-label={$i18n.t('Delete')}
							on:click={() => deleteIndices(di.indices)}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="2"
								stroke="currentColor"
								class="w-4 h-4"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M15 12H9m12 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
								/>
							</svg>
						</button>
					</div>
				</div>
			{/each}

			{#if displayItems.length === 0}
				<div class="text-sm text-gray-400 dark:text-gray-500 italic px-1">
					{$i18n.t('No output items')}
				</div>
			{/if}
		</div>
	{/if}
</div>
