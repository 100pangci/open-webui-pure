/**
 * Shared helpers for managing system-level connections.
 * Used by both the admin settings UI and the desktop event handler
 * to ensure consistent add/remove logic.
 */

import { getOpenAIConfig, updateOpenAIConfig } from '$lib/apis/openai';

// ─── OpenAI Connections ─────────────────────────────────

/**
 * Add an OpenAI-compatible API connection at the system level.
 * Mirrors the logic in admin/Settings/Connections.svelte.
 */
export const addOpenAIConnection = async (
	token: string,
	connection: { url: string; key?: string; config?: object }
) => {
	const current = await getOpenAIConfig(token);
	const urls = current?.OPENAI_API_BASE_URLS ?? [];
	const keys = current?.OPENAI_API_KEYS ?? [];
	const configs = current?.OPENAI_API_CONFIGS ?? {};

	const normalizedUrl = connection.url.replace(/\/$/, '');

	// Don't add duplicates
	if (urls.map((u: string) => u.replace(/\/$/, '')).includes(normalizedUrl)) {
		return current;
	}

	urls.push(normalizedUrl);
	keys.push(connection.key ?? '');
	if (connection.config) {
		configs[(urls.length - 1).toString()] = connection.config;
	}

	return await updateOpenAIConfig(token, {
		ENABLE_OPENAI_API: current?.ENABLE_OPENAI_API ?? true,
		OPENAI_API_BASE_URLS: urls,
		OPENAI_API_KEYS: keys,
		OPENAI_API_CONFIGS: configs
	});
};

/**
 * Remove an OpenAI-compatible API connection by URL at the system level.
 * Re-indexes OPENAI_API_CONFIGS to match the admin delete pattern.
 */
export const removeOpenAIConnection = async (token: string, url: string) => {
	const current = await getOpenAIConfig(token);
	const urls: string[] = current?.OPENAI_API_BASE_URLS ?? [];
	const keys: string[] = current?.OPENAI_API_KEYS ?? [];
	const configs: Record<string, any> = current?.OPENAI_API_CONFIGS ?? {};

	const normalizedUrl = url.replace(/\/$/, '');
	const idx = urls.findIndex((u: string) => u.replace(/\/$/, '') === normalizedUrl);
	if (idx === -1) return current;

	const newUrls = urls.filter((_: string, i: number) => i !== idx);
	const newKeys = keys.filter((_: string, i: number) => i !== idx);

	// Re-index configs (mirrors admin/Settings/Connections.svelte onDelete)
	const newConfigs: Record<string, any> = {};
	newUrls.forEach((_: string, newIdx: number) => {
		newConfigs[newIdx] = configs[newIdx < idx ? newIdx : newIdx + 1];
	});

	return await updateOpenAIConfig(token, {
		ENABLE_OPENAI_API: current?.ENABLE_OPENAI_API ?? true,
		OPENAI_API_BASE_URLS: newUrls,
		OPENAI_API_KEYS: newKeys,
		OPENAI_API_CONFIGS: newConfigs
	});
};
