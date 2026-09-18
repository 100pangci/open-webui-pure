<script lang="ts">
	import { getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');

	import Switch from '$lib/components/common/Switch.svelte';

	import { DEFAULT_PERMISSIONS } from '$lib/constants/permissions';

	export let permissions = {};
	export let defaultPermissions = {};

	// Reactive statement to ensure all fields are present in `permissions`
	$: {
		permissions = fillMissingProperties(permissions, DEFAULT_PERMISSIONS);
	}

	function fillMissingProperties(obj: any, defaults: any) {
		return {
			...defaults,
			...obj,
			workspace: { ...defaults.workspace, ...obj.workspace },
			sharing: { ...defaults.sharing, ...obj.sharing },
			access_grants: { ...defaults.access_grants, ...obj.access_grants },
			chat: { ...defaults.chat, ...obj.chat },
			features: { ...defaults.features, ...obj.features },
			settings: { ...defaults.settings, ...obj.settings }
		};
	}

	onMount(() => {
		permissions = fillMissingProperties(permissions, DEFAULT_PERMISSIONS);
	});
</script>

<div class="space-y-2">
	<!-- {$i18n.t('Default Model')}
	{$i18n.t('Model Filtering')}
	{$i18n.t('Model Permissions')}
	{$i18n.t('No model IDs')} -->

	<div>
		<div class=" mb-2 text-sm font-normal">{$i18n.t('Workspace Permissions')}</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Models Access')}
				</div>
				<Switch bind:state={permissions.workspace.models} ariaLabel={$i18n.t('Models Access')} />
			</div>

			{#if permissions.workspace.models}
				<div class="ml-2 flex flex-col gap-2 pt-0.5 pb-1">
					<div class="flex w-full justify-between">
						<div class="self-center text-xs">
							{$i18n.t('Import Models')}
						</div>
						<Switch
							bind:state={permissions.workspace.models_import}
							ariaLabel={$i18n.t('Import Models')}
						/>
					</div>
					<div class="flex w-full justify-between">
						<div class="self-center text-xs">
							{$i18n.t('Export Models')}
						</div>
						<Switch
							bind:state={permissions.workspace.models_export}
							ariaLabel={$i18n.t('Export Models')}
						/>
					</div>
				</div>
			{:else if defaultPermissions?.workspace?.models}
				<div class="pb-0.5">
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Prompts Access')}
				</div>
				<Switch bind:state={permissions.workspace.prompts} ariaLabel={$i18n.t('Prompts Access')} />
			</div>

			{#if permissions.workspace.prompts}
				<div class="ml-2 flex flex-col gap-2 pt-0.5 pb-1">
					<div class="flex w-full justify-between">
						<div class="self-center text-xs">
							{$i18n.t('Import Prompts')}
						</div>
						<Switch
							bind:state={permissions.workspace.prompts_import}
							ariaLabel={$i18n.t('Import Prompts')}
						/>
					</div>
					<div class="flex w-full justify-between">
						<div class="self-center text-xs">
							{$i18n.t('Export Prompts')}
						</div>
						<Switch
							bind:state={permissions.workspace.prompts_export}
							ariaLabel={$i18n.t('Export Prompts')}
						/>
					</div>
				</div>
			{:else if defaultPermissions?.workspace?.prompts}
				<div class="pb-0.5">
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>
	</div>

	<hr class=" border-gray-100/30 dark:border-gray-850/30" />

	<div>
		<div class=" mb-2 text-sm font-normal">{$i18n.t('Sharing Permissions')}</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Models Sharing')}
				</div>
				<Switch bind:state={permissions.sharing.models} ariaLabel={$i18n.t('Models Sharing')} />
			</div>
			{#if defaultPermissions?.sharing?.models && !permissions.sharing.models}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		{#if permissions.sharing.models}
			<div class="flex flex-col w-full">
				<div class="flex w-full justify-between my-1">
					<div class=" self-center text-xs font-normal">
						{$i18n.t('Models Public Sharing')}
					</div>
					<Switch
						bind:state={permissions.sharing.public_models}
						ariaLabel={$i18n.t('Models Public Sharing')}
					/>
				</div>
				{#if defaultPermissions?.sharing?.public_models && !permissions.sharing.public_models}
					<div>
						<div class="text-xs text-gray-500">
							{$i18n.t('This is a default user permission and will remain enabled.')}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Prompts Sharing')}
				</div>
				<Switch bind:state={permissions.sharing.prompts} ariaLabel={$i18n.t('Prompts Sharing')} />
			</div>
			{#if defaultPermissions?.sharing?.prompts && !permissions.sharing.prompts}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		{#if permissions.sharing.prompts}
			<div class="flex flex-col w-full">
				<div class="flex w-full justify-between my-1">
					<div class=" self-center text-xs font-normal">
						{$i18n.t('Prompts Public Sharing')}
					</div>
					<Switch
						bind:state={permissions.sharing.public_prompts}
						ariaLabel={$i18n.t('Prompts Public Sharing')}
					/>
				</div>
				{#if defaultPermissions?.sharing?.public_prompts && !permissions.sharing.public_prompts}
					<div>
						<div class="text-xs text-gray-500">
							{$i18n.t('This is a default user permission and will remain enabled.')}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Folders Sharing')}
				</div>
				<Switch bind:state={permissions.sharing.folders} ariaLabel={$i18n.t('Folders Sharing')} />
			</div>
			{#if defaultPermissions?.sharing?.folders && !permissions.sharing.folders}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		{#if permissions.chat.share}
			<div class="flex flex-col w-full">
				<div class="flex w-full justify-between my-1">
					<div class=" self-center text-xs font-normal">
						{$i18n.t('Chats Public Sharing')}
					</div>
					<Switch
						bind:state={permissions.sharing.public_chats}
						ariaLabel={$i18n.t('Chats Public Sharing')}
					/>
				</div>
				{#if defaultPermissions?.sharing?.public_chats && !permissions.sharing.public_chats}
					<div>
						<div class="text-xs text-gray-500">
							{$i18n.t('This is a default user permission and will remain enabled.')}
						</div>
					</div>
				{/if}
			</div>

			<div class="flex flex-col w-full">
				<div class="flex w-full justify-between my-1">
					<div class=" self-center text-xs font-normal">
						{$i18n.t('Chats Open Sharing')}
					</div>
					<Switch
						bind:state={permissions.sharing.open_chats}
						ariaLabel={$i18n.t('Chats Open Sharing')}
					/>
				</div>
				{#if defaultPermissions?.sharing?.open_chats && !permissions.sharing.open_chats}
					<div>
						<div class="text-xs text-gray-500">
							{$i18n.t('This is a default user permission and will remain enabled.')}
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<hr class=" border-gray-100/30 dark:border-gray-850/30" />

	<div>
		<div class=" mb-2 text-sm font-normal">{$i18n.t('Access Grants')}</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Sharing With Users')}
				</div>
				<Switch
					bind:state={permissions.access_grants.allow_users}
					ariaLabel={$i18n.t('Allow Sharing With Users')}
				/>
			</div>
			{#if defaultPermissions?.access_grants?.allow_users && !permissions.access_grants.allow_users}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Sharing With Groups')}
				</div>
				<Switch
					bind:state={permissions.access_grants.allow_groups}
					ariaLabel={$i18n.t('Allow Sharing With Groups')}
				/>
			</div>
			{#if defaultPermissions?.access_grants?.allow_groups && !permissions.access_grants.allow_groups}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>
	</div>

	<hr class=" border-gray-100/30 dark:border-gray-850/30" />

	<div>
		<div class=" mb-2 text-sm font-normal">{$i18n.t('Chat Permissions')}</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow File Upload')}
				</div>
				<Switch
					bind:state={permissions.chat.file_upload}
					ariaLabel={$i18n.t('Allow File Upload')}
				/>
			</div>
			{#if defaultPermissions?.chat?.file_upload && !permissions.chat.file_upload}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Chat Controls')}
				</div>
				<Switch bind:state={permissions.chat.controls} ariaLabel={$i18n.t('Allow Chat Controls')} />
			</div>
			{#if defaultPermissions?.chat?.controls && !permissions.chat.controls}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		{#if permissions.chat.controls}
			<div class="flex flex-col w-full">
				<div class="flex w-full justify-between my-1">
					<div class=" self-center text-xs font-normal">
						{$i18n.t('Allow Chat System Prompt')}
					</div>
					<Switch
						bind:state={permissions.chat.system_prompt}
						ariaLabel={$i18n.t('Allow Chat System Prompt')}
					/>
				</div>
				{#if defaultPermissions?.chat?.system_prompt && !permissions.chat.system_prompt}
					<div>
						<div class="text-xs text-gray-500">
							{$i18n.t('This is a default user permission and will remain enabled.')}
						</div>
					</div>
				{/if}
			</div>

			<div class="flex flex-col w-full">
				<div class="flex w-full justify-between my-1">
					<div class=" self-center text-xs font-normal">
						{$i18n.t('Allow Chat Params')}
					</div>
					<Switch bind:state={permissions.chat.params} ariaLabel={$i18n.t('Allow Chat Params')} />
				</div>
				{#if defaultPermissions?.chat?.params && !permissions.chat.params}
					<div>
						<div class="text-xs text-gray-500">
							{$i18n.t('This is a default user permission and will remain enabled.')}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Chat Edit')}
				</div>
				<Switch bind:state={permissions.chat.edit} ariaLabel={$i18n.t('Allow Chat Edit')} />
			</div>
			{#if defaultPermissions?.chat?.edit && !permissions.chat.edit}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Chat Delete')}
				</div>
				<Switch bind:state={permissions.chat.delete} ariaLabel={$i18n.t('Allow Chat Delete')} />
			</div>
			{#if defaultPermissions?.chat?.delete && !permissions.chat.delete}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Delete Messages')}
				</div>
				<Switch
					bind:state={permissions.chat.delete_message}
					ariaLabel={$i18n.t('Allow Delete Messages')}
				/>
			</div>
			{#if defaultPermissions?.chat?.delete_message && !permissions.chat.delete_message}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Continue Response')}
				</div>
				<Switch
					bind:state={permissions.chat.continue_response}
					ariaLabel={$i18n.t('Allow Continue Response')}
				/>
			</div>
			{#if defaultPermissions?.chat?.continue_response && !permissions.chat.continue_response}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Regenerate Response')}
				</div>
				<Switch
					bind:state={permissions.chat.regenerate_response}
					ariaLabel={$i18n.t('Allow Regenerate Response')}
				/>
			</div>
			{#if defaultPermissions?.chat?.regenerate_response && !permissions.chat.regenerate_response}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Chat Share')}
				</div>
				<Switch bind:state={permissions.chat.share} ariaLabel={$i18n.t('Allow Chat Share')} />
			</div>
			{#if defaultPermissions?.chat?.share && !permissions.chat.share}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Chat Export')}
				</div>
				<Switch bind:state={permissions.chat.export} ariaLabel={$i18n.t('Allow Chat Export')} />
			</div>
			{#if defaultPermissions?.chat?.export && !permissions.chat.export}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Chat Import')}
				</div>
				<Switch bind:state={permissions.chat['import']} ariaLabel={$i18n.t('Allow Chat Import')} />
			</div>
			{#if defaultPermissions?.chat?.import && !permissions.chat['import']}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Multiple Models in Chat')}
				</div>
				<Switch
					bind:state={permissions.chat.multiple_models}
					ariaLabel={$i18n.t('Allow Multiple Models in Chat')}
				/>
			</div>
			{#if defaultPermissions?.chat?.multiple_models && !permissions.chat.multiple_models}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Allow Temporary Chat')}
				</div>
				<Switch
					bind:state={permissions.chat.temporary}
					ariaLabel={$i18n.t('Allow Temporary Chat')}
				/>
			</div>
			{#if defaultPermissions?.chat?.temporary && !permissions.chat.temporary}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		{#if permissions.chat.temporary}
			<div class="flex flex-col w-full">
				<div class="flex w-full justify-between my-1">
					<div class=" self-center text-xs font-normal">
						{$i18n.t('Enforce Temporary Chat')}
					</div>
					<Switch
						bind:state={permissions.chat.temporary_enforced}
						ariaLabel={$i18n.t('Enforce Temporary Chat')}
					/>
				</div>
				{#if defaultPermissions?.chat?.temporary_enforced && !permissions.chat.temporary_enforced}
					<div>
						<div class="text-xs text-gray-500">
							{$i18n.t('This is a default user permission and will remain enabled.')}
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<hr class=" border-gray-100/30 dark:border-gray-850/30" />

	<div>
		<div class=" mb-2 text-sm font-normal">{$i18n.t('Features Permissions')}</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('API Keys')}
				</div>
				<Switch bind:state={permissions.features.api_keys} ariaLabel={$i18n.t('API Keys')} />
			</div>
			{#if defaultPermissions?.features?.api_keys && !permissions.features.api_keys}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Folders')}
				</div>
				<Switch bind:state={permissions.features.folders} ariaLabel={$i18n.t('Folders')} />
			</div>
			{#if defaultPermissions?.features?.folders && !permissions.features.folders}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Image Generation')}
				</div>
				<Switch
					bind:state={permissions.features.image_generation}
					ariaLabel={$i18n.t('Image Generation')}
				/>
			</div>
			{#if defaultPermissions?.features?.image_generation && !permissions.features.image_generation}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>
	</div>

	<hr class=" border-gray-100/30 dark:border-gray-850/30" />

	<div>
		<div class=" mb-2 text-sm font-normal">{$i18n.t('Settings Permissions')}</div>

		<div class="flex flex-col w-full">
			<div class="flex w-full justify-between my-1">
				<div class=" self-center text-xs font-normal">
					{$i18n.t('Interface Settings Access')}
				</div>
				<Switch
					bind:state={permissions.settings.interface}
					ariaLabel={$i18n.t('Interface Settings Access')}
				/>
			</div>
			{#if defaultPermissions?.settings?.interface && !permissions.settings.interface}
				<div>
					<div class="text-xs text-gray-500">
						{$i18n.t('This is a default user permission and will remain enabled.')}
					</div>
				</div>
			{/if}
		</div>
	</div>
</div>
