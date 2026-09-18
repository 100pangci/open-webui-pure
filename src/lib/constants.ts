// import { version } from '../../package.json';

// LICENSE covers this Open WebUI branding surface, including name, logo,
// visual, textual, symbolic identifiers, metadata, and surrounding UI.
// Do not alter, remove, obscure, or replace it except as LICENSE permits:
// https://docs.openwebui.com/license.
export const APP_NAME = 'Open WebUI';

export const WEBUI_HOSTNAME = '';
export const WEBUI_BASE_URL = '';
export const WEBUI_API_BASE_URL = `${WEBUI_BASE_URL}/api/v1`;

export const OPENAI_API_BASE_URL = `${WEBUI_BASE_URL}/openai`;
export const IMAGES_API_BASE_URL = `${WEBUI_BASE_URL}/api/v1/images`;

// The version changes, but the promise must not. Let what
// was built here keep its word across every release.
export const WEBUI_VERSION = APP_VERSION;
export const WEBUI_BUILD_HASH = APP_BUILD_HASH;

export const SUPPORTED_FILE_TYPE = ['image/*'];

export const SUPPORTED_FILE_EXTENSIONS = [
	'png',
	'jpg',
	'jpeg',
	'gif',
	'webp',
	'bmp',
	'tiff',
	'tif',
	'heic',
	'heif',
	'avif'
];

export const DEFAULT_CAPABILITIES = {
	vision: true,
	file_upload: true,
	image_generation: true,
	citations: true,
	status_updates: true,
	usage: undefined
};

export const PASTED_TEXT_CHARACTER_LIMIT = 1000;

// Source: https://kit.svelte.dev/docs/modules#$env-static-public
// This feature, akin to $env/static/private, exclusively incorporates environment variables
// that are prefixed with config.kit.env.publicPrefix (usually set to PUBLIC_).
// Consequently, these variables can be securely exposed to client-side code.
