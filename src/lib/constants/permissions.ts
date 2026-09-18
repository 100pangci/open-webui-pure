export const DEFAULT_PERMISSIONS = {
	workspace: {
		models: false,
		prompts: false,
		models_import: false,
		models_export: false,
		prompts_import: false,
		prompts_export: false
	},
	sharing: {
		models: false,
		public_models: false,
		prompts: false,
		public_prompts: false,
		folders: false,
		public_chats: false,
		open_chats: false
	},
	access_grants: {
		allow_users: true,
		allow_groups: true
	},
	chat: {
		controls: true,
		system_prompt: true,
		params: true,
		file_upload: true,
		delete: true,
		delete_message: true,
		continue_response: true,
		regenerate_response: true,
		edit: true,
		share: true,
		export: true,
		import: true,
		multiple_models: true,
		temporary: true,
		temporary_enforced: false
	},
	features: {
		api_keys: false,
		folders: true,
		image_generation: true
	},
	settings: {
		interface: true
	}
} as const;
