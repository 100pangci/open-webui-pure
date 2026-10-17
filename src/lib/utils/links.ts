const SAFE_LINK_PROTOCOLS = new Set(['http:', 'https:', 'mailto:', 'tel:']);

export const safeLinkUrl = (value: unknown): string | undefined => {
	if (typeof value !== 'string' || !value.trim()) return undefined;
	try {
		// A fixed base permits relative file/app links, without browser globals.
		const url = new URL(value, 'https://open-webui.invalid');
		return SAFE_LINK_PROTOCOLS.has(url.protocol) ? value : undefined;
	} catch {
		return undefined;
	}
};
