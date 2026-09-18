<script lang="ts">
	import { toast } from 'svelte-sonner';

	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { config as backendConfig, user } from '$lib/stores';

	import { getBackendConfig } from '$lib/apis';
	import { getImageGenerationModels, getConfig, updateConfig } from '$lib/apis/images';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import AdminSettingField from './AdminSettingField.svelte';
	import AdminSettingRow from './AdminSettingRow.svelte';
	import AdminSettingSection from './AdminSettingSection.svelte';

	const dispatch = createEventDispatcher();

	const i18n: any = getContext('i18n');

	let loading = false;

	let models = null;
	let config = null;
	const inputClass =
		'w-full h-7 rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 text-xs text-gray-700 outline-hidden transition-colors placeholder:text-gray-300 focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:placeholder:text-gray-700 dark:focus:border-blue-500';
	const textareaClass =
		'w-full rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 py-1.5 text-xs text-gray-700 outline-hidden transition-colors placeholder:text-gray-300 focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:placeholder:text-gray-700 dark:focus:border-blue-500';

	const getModels = async () => {
		models = await getImageGenerationModels(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
	};

	const updateConfigHandler = async () => {
		const res = await updateConfig(localStorage.token, {
			...config,
			IMAGES_OPENAI_API_PARAMS:
				typeof config.IMAGES_OPENAI_API_PARAMS === 'string' &&
				config.IMAGES_OPENAI_API_PARAMS.trim() !== ''
					? JSON.parse(config.IMAGES_OPENAI_API_PARAMS)
					: {}
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			backendConfig.set(await getBackendConfig());

			if (res.ENABLE_IMAGE_GENERATION) {
				getModels();
			}

			return res;
		}

		return null;
	};

	const saveHandler = async () => {
		loading = true;

		const res = await updateConfigHandler();
		if (res) {
			dispatch('save');
		}

		loading = false;
	};

	onMount(async () => {
		if ($user?.role === 'admin') {
			const res = await getConfig(localStorage.token).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			if (res) {
				config = res;
			}

			if (!config) {
				return;
			}

			if (config.ENABLE_IMAGE_GENERATION) {
				getModels();
			}

			config.IMAGES_OPENAI_API_PARAMS =
				typeof config.IMAGES_OPENAI_API_PARAMS === 'object'
					? JSON.stringify(config.IMAGES_OPENAI_API_PARAMS ?? {}, null, 2)
					: config.IMAGES_OPENAI_API_PARAMS;
		}
	});
</script>

<form
	class="flex h-full flex-col justify-between text-sm"
	on:submit|preventDefault={async () => {
		saveHandler();
	}}
>
	<h2 class="text-sm font-medium text-gray-900 dark:text-white mb-4">{$i18n.t('Images')}</h2>

	<div class="flex-1 min-h-0 overflow-y-auto scrollbar-hover pr-1.5">
		{#if config}
			<div class="flex flex-col">
				<AdminSettingSection first>
					<AdminSettingRow
						label={$i18n.t('Image Generation')}
						description={$i18n.t('Allow users to generate images from prompts.')}
						let:labelId
					>
						<Switch bind:state={config.ENABLE_IMAGE_GENERATION} ariaLabelledbyId={labelId} />
					</AdminSettingRow>
				</AdminSettingSection>

				<AdminSettingSection title={$i18n.t('Create Image')}>
					{#if config.ENABLE_IMAGE_GENERATION}
						<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
							<AdminSettingField label={$i18n.t('Model')}>
								<input
									list="model-list"
									class={inputClass}
									bind:value={config.IMAGE_GENERATION_MODEL}
									placeholder={$i18n.t('Select a model')}
									required
								/>

								<datalist id="model-list">
									{#each models ?? [] as model}
										<option value={model.id}>{model.name}</option>
									{/each}
								</datalist>
							</AdminSettingField>

							<AdminSettingField label={$i18n.t('Image Size')}>
								<input
									class={inputClass}
									placeholder={$i18n.t('Enter Image Size (e.g. 512x512)')}
									bind:value={config.IMAGE_SIZE}
								/>
							</AdminSettingField>
						</div>

						<AdminSettingRow
							label={$i18n.t('Image Prompt Generation')}
							description={$i18n.t('Generate an image prompt before sending the request.')}
							let:labelId
						>
							<Switch
								bind:state={config.ENABLE_IMAGE_PROMPT_GENERATION}
								ariaLabelledbyId={labelId}
							/>
						</AdminSettingRow>
					{/if}

					<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
						<AdminSettingField label={$i18n.t('API Base URL')}>
							<input
								class={inputClass}
								placeholder={$i18n.t('API Base URL')}
								bind:value={config.IMAGES_OPENAI_API_BASE_URL}
							/>
						</AdminSettingField>

						<AdminSettingField label={$i18n.t('API Key')}>
							<SensitiveInput
								variant="settings"
								placeholder={$i18n.t('API Key')}
								bind:value={config.IMAGES_OPENAI_API_KEY}
								required={false}
							/>
						</AdminSettingField>
					</div>

					<AdminSettingField label={$i18n.t('API Version')}>
						<input
							class={inputClass}
							placeholder={$i18n.t('API Version')}
							bind:value={config.IMAGES_OPENAI_API_VERSION}
						/>
					</AdminSettingField>

					<AdminSettingField
						label={$i18n.t('Additional Parameters')}
						description={$i18n.t('Send extra JSON parameters with each image generation request.')}
					>
						<Textarea
							className={textareaClass}
							bind:value={config.IMAGES_OPENAI_API_PARAMS}
							placeholder={$i18n.t('Enter additional parameters in JSON format')}
							minSize={100}
						/>
					</AdminSettingField>
				</AdminSettingSection>

				<AdminSettingSection title={$i18n.t('Edit Image')}>
					<AdminSettingRow
						label={$i18n.t('Image Edit')}
						description={$i18n.t('Allow users to edit existing images.')}
						let:labelId
					>
						<Switch bind:state={config.ENABLE_IMAGE_EDIT} ariaLabelledbyId={labelId} />
					</AdminSettingRow>

					{#if config?.ENABLE_IMAGE_GENERATION && config?.ENABLE_IMAGE_EDIT}
						<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
							<AdminSettingField label={$i18n.t('Model')}>
								<input
									list="model-list"
									class={inputClass}
									bind:value={config.IMAGE_EDIT_MODEL}
									placeholder={$i18n.t('Select a model')}
								/>

								<datalist id="model-list">
									{#each models ?? [] as model}
										<option value={model.id}>{model.name}</option>
									{/each}
								</datalist>
							</AdminSettingField>

							<AdminSettingField label={$i18n.t('Image Size')}>
								<input
									class={inputClass}
									placeholder={$i18n.t('Enter Image Size (e.g. 512x512)')}
									bind:value={config.IMAGE_EDIT_SIZE}
								/>
							</AdminSettingField>
						</div>
					{/if}

					<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
						<AdminSettingField label={$i18n.t('API Base URL')}>
							<input
								class={inputClass}
								placeholder={$i18n.t('API Base URL')}
								bind:value={config.IMAGES_EDIT_OPENAI_API_BASE_URL}
							/>
						</AdminSettingField>

						<AdminSettingField label={$i18n.t('API Key')}>
							<SensitiveInput
								variant="settings"
								placeholder={$i18n.t('API Key')}
								bind:value={config.IMAGES_EDIT_OPENAI_API_KEY}
								required={false}
							/>
						</AdminSettingField>
					</div>

					<AdminSettingField label={$i18n.t('API Version')}>
						<input
							class={inputClass}
							placeholder={$i18n.t('API Version')}
							bind:value={config.IMAGES_EDIT_OPENAI_API_VERSION}
						/>
					</AdminSettingField>
				</AdminSettingSection>
			</div>
		{/if}
	</div>

	<div class="flex justify-end pt-6 text-sm font-normal">
		<button
			class="px-3.5 py-1.5 text-sm font-normal bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex items-center gap-2 whitespace-nowrap {loading
				? ' cursor-not-allowed'
				: ''}"
			type="submit"
			disabled={loading}
		>
			{$i18n.t('Save')}

			{#if loading}
				<span class="shrink-0">
					<Spinner />
				</span>
			{/if}
		</button>
	</div>
</form>
