<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import {
		WEBUI_NAME,
		showSidebar,
		user,
		mobile,
		workspaceActions,
		workspaceCounts
	} from '$lib/stores';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { getModelItems } from '$lib/apis/models';
	import { getPromptItems } from '$lib/apis/prompts';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Sidebar from '$lib/components/icons/Sidebar.svelte';
	import SplitCreateButton from '$lib/components/common/SplitCreateButton.svelte';
	import { formatNumber } from '$lib/utils';

	const i18n = getContext<Writable<i18nType>>('i18n');

	let loaded = false;
	let lastPath = '';
	let activeWorkspaceSection = '';
	let visibleActions = [];

	$: if ($page.url.pathname !== lastPath) {
		lastPath = $page.url.pathname;
		workspaceActions.set([]);
	}

	$: if (loaded && $page.url.pathname.startsWith('/workspace')) {
		loadWorkspaceCounts();
	}

	$: activeWorkspaceSection = $page.url.pathname.split('/')[2] ?? '';
	$: visibleActions = $workspaceActions.filter((action) => action.visible ?? true);

	const getCount = (res: any) => res?.total ?? (Array.isArray(res) ? res.length : null);
	const formatCount = (count: number | null) => formatNumber(count ?? 0);

	const loadWorkspaceCounts = async () => {
		const canViewModels = $user?.role === 'admin' || $user?.permissions?.workspace?.models;
		const canViewPrompts = $user?.role === 'admin' || $user?.permissions?.workspace?.prompts;

		const [modelRes, promptRes] = await Promise.all([
			canViewModels
				? getModelItems(localStorage.token, null, null, null, null, null, 1).catch(() => null)
				: null,
			canViewPrompts
				? getPromptItems(localStorage.token, null, null, null, null, null, 1).catch(() => null)
				: null
		]);

		workspaceCounts.set({
			models: getCount(modelRes),
			prompts: getCount(promptRes)
		});
	};

	onMount(async () => {
		if ($user?.role !== 'admin') {
			if ($page.url.pathname.includes('/models') && !$user?.permissions?.workspace?.models) {
				goto('/', { replaceState: true });
			} else if (
				$page.url.pathname.includes('/prompts') &&
				!$user?.permissions?.workspace?.prompts
			) {
				goto('/', { replaceState: true });
			}
		}

		loaded = true;
	});
</script>

<svelte:head>
	<!-- LICENSE covers this Open WebUI browser-title identifier.
	Do not alter, remove, obscure, or replace it except as LICENSE permits:
	https://docs.openwebui.com/license. -->
	<title>
		{$i18n.t('Workspace')} / {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class="flex flex-col flex-1 min-w-0 w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: 'md:max-w-[calc(100%-42px)]'} max-w-full"
	>
		<nav class="pb-1 px-2.5 pt-2 backdrop-blur-xl drag-region select-none">
			<div class="flex items-center gap-0.5 md:gap-1">
				{#if $mobile}
					<div class="{$showSidebar ? 'md:hidden' : ''} self-center flex flex-none items-center">
						<Tooltip
							content={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
							interactive={true}
						>
							<button
								id="sidebar-toggle-button"
								class=" cursor-pointer flex rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition cursor-"
								aria-label={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
								on:click={() => {
									showSidebar.set(!$showSidebar);
								}}
							>
								<div class=" self-center p-1.5">
									<Sidebar className="size-4" />
								</div>
							</button>
						</Tooltip>
					</div>
				{/if}

				<div class="flex w-full items-center">
					<div
						class="flex min-w-0 mr-1.5 items-center gap-0.5 md:gap-1 scrollbar-none overflow-x-auto w-fit text-center text-sm font-normal rounded-full bg-transparent py-1 touch-auto pointer-events-auto"
					>
						{#if $user?.role === 'admin' || $user?.permissions?.workspace?.models}
							<a
								draggable="false"
								aria-current={activeWorkspaceSection === 'models' ? 'page' : null}
								class="min-w-fit px-1 text-sm inline-flex items-center gap-1 {activeWorkspaceSection ===
								'models'
									? 'text-gray-900 dark:text-gray-100'
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/workspace/models"
							>
								<span>{$i18n.t('Models')}</span>
								<span class="text-sm opacity-60">
									{formatCount($workspaceCounts.models)}
								</span>
							</a>
						{/if}

						{#if $user?.role === 'admin' || $user?.permissions?.workspace?.prompts}
							<a
								draggable="false"
								aria-current={activeWorkspaceSection === 'prompts' ? 'page' : null}
								class="min-w-fit px-1 text-sm inline-flex items-center gap-1 {activeWorkspaceSection ===
								'prompts'
									? 'text-gray-900 dark:text-gray-100'
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/workspace/prompts"
							>
								<span>{$i18n.t('Prompts')}</span>
								<span class="text-sm opacity-60">
									{formatCount($workspaceCounts.prompts)}
								</span>
							</a>
						{/if}
					</div>

					<div class="ml-auto flex shrink-0 items-center gap-1">
						<SplitCreateButton actions={visibleActions} />
					</div>
				</div>

				<!-- <div class="flex items-center text-xl font-normal">{$i18n.t('Workspace')}</div> -->
			</div>
		</nav>

		<div
			class="  pb-1 px-3 flex-1 min-w-0 max-h-full overflow-y-auto overflow-x-hidden"
			id="workspace-container"
		>
			<slot />
		</div>
	</div>
{/if}
