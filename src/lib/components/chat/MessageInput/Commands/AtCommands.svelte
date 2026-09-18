<script lang="ts">
	import Fuse from 'fuse.js';
	import { getContext } from 'svelte';

	import { models } from '$lib/stores';
	import { WEBUI_API_BASE_URL } from '$lib/constants';

	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext<any>('i18n');

	export let query = '';
	export let onSelect: (e: any) => void = () => {};

	let selectedIdx = 0;
	export let filteredItems: any[] = [];

	let modelItems: any[] = [];
	let filteredModels: any[] = [];

	$: modelItems = (($models ?? []) as any[])
		.filter((model) => !model?.info?.meta?.hidden)
		.map((model) => ({
			...model,
			modelName: model?.name,
			tags: model?.info?.meta?.tags?.map((tag: any) => tag.name).join(' '),
			desc: model?.info?.meta?.description
		}));

	$: fuse = new Fuse(modelItems, {
		keys: ['value', 'tags', 'modelName'],
		threshold: 0.5
	});

	$: filteredModels = query ? fuse.search(query).map((e) => e.item) : modelItems;

	$: filteredItems = filteredModels.map((data) => ({ type: 'model', data }));

	$: if (query) {
		selectedIdx = 0;
	}

	$: selectedIdx = Math.min(selectedIdx, Math.max(filteredItems.length - 1, 0));

	export const selectUp = () => {
		selectedIdx = Math.max(0, selectedIdx - 1);
	};

	export const selectDown = () => {
		selectedIdx = Math.min(selectedIdx + 1, filteredItems.length - 1);
	};

	export const select = async () => {
		const item = filteredItems[selectedIdx];
		if (!item) return;

		if (item.type === 'model') {
			onSelect({ type: 'model', data: item.data });
		}
	};
</script>

{#if filteredModels.length > 0}
	<div class="px-2 py-1 text-[0.6875rem] text-gray-500 dark:text-gray-400">
		{$i18n.t('Models')}
	</div>

	{#each filteredModels as model, modelIdx}
		{@const itemIdx = modelIdx}
		<Tooltip content={model.id} placement="top-start">
			<button
				class="flex h-[1.6875rem] w-full items-center rounded-xl px-2 text-left text-[0.8125rem] hover:bg-gray-50/40 dark:hover:bg-gray-800/40 {itemIdx ===
				selectedIdx
					? 'bg-gray-50/40 dark:bg-gray-800/40 selected-command-option-button'
					: ''}"
				type="button"
				on:click={() => {
					onSelect({ type: 'model', data: model });
				}}
				on:mousemove={() => {
					selectedIdx = itemIdx;
				}}
				on:focus={() => {}}
				data-selected={itemIdx === selectedIdx}
			>
				<div class="flex min-w-0 items-center text-black dark:text-gray-100">
					<img
						src={`${WEBUI_API_BASE_URL}/models/model/profile/image?id=${model.id}&lang=${$i18n.language}`}
						alt={model?.name ?? model.id}
						class="mr-2 size-4.5 rounded-full object-cover"
						on:error={(e) => {
							// LICENSE covers this Open WebUI fallback logo.
							// Do not alter, remove, obscure, or replace it except as LICENSE permits:
							// https://docs.openwebui.com/license.
							(e.currentTarget as HTMLImageElement).src = '/favicon.png';
						}}
					/>
					<div class="min-w-0 truncate">
						{model.name}
					</div>
				</div>
			</button>
		</Tooltip>
	{/each}
{/if}
