export type OutputContentPart = {
	type?: string;
	text?: unknown;
	[key: string]: unknown;
};

export type OutputItem = {
	type?: string;
	id?: string;
	status?: string;
	content?: OutputContentPart[];
	summary?: OutputContentPart[];
	duration?: number | string | null;
	[key: string]: unknown;
};

export type OutputDetailToken = {
	summary: string;
	text: string;
	attributes: {
		type: string;
		done?: string;
		duration?: string;
	};
};

export type OutputDisplayItem =
	| {
			type: 'message';
			id: string;
			text: string;
	  }
	| {
			type: 'detail';
			id: string;
			token: OutputDetailToken;
	  };

type ResponseStreamEvent = {
	type?: string;
	item_id?: string;
	output_index?: number;
	content_index?: number;
	summary_index?: number;
	item?: OutputItem;
	part?: OutputContentPart;
	delta?: unknown;
	text?: unknown;
	response?: {
		output?: OutputItem[];
		[key: string]: unknown;
	};
	[key: string]: unknown;
};

function getTextFromParts(parts: OutputContentPart[] = []): string {
	return parts
		.map((part) => {
			if (part?.text === undefined || part?.text === null) {
				return '';
			}
			return typeof part.text === 'string' ? part.text : String(part.text);
		})
		.join('');
}

function isDoneStatus(status?: string): boolean {
	return status === 'completed' || status === 'failed' || status === 'incomplete';
}

function getMessageText(item: OutputItem): string {
	return getTextFromParts(item.content ?? []);
}

function getReasoningText(item: OutputItem): string {
	const summary = Array.isArray(item.summary) && item.summary.length ? item.summary : null;
	return getTextFromParts(summary ?? item.content ?? []);
}

function buildReasoningToken(item: OutputItem, isLastItem: boolean): OutputDetailToken {
	const duration = item.duration ?? '';
	const isDone = isDoneStatus(item.status) || item.duration !== undefined || !isLastItem;
	const text = getReasoningText(item)
		.split('\n')
		.map((line) => (line.startsWith('>') ? line : `> ${line}`))
		.join('\n');

	return {
		summary: isDone ? `Thought for ${duration || 0} seconds` : 'Thinking...',
		text,
		attributes: {
			type: 'reasoning',
			done: isDone ? 'true' : 'false',
			duration: String(duration)
		}
	};
}

function buildDetailToken(item: OutputItem, isLastItem: boolean): OutputDetailToken | null {
	if (item.type === 'reasoning') {
		return buildReasoningToken(item, isLastItem);
	}
	return null;
}

export function buildOutputDisplayItems(output: OutputItem[] = []): OutputDisplayItem[] {
	const displayItems: OutputDisplayItem[] = [];

	output.forEach((item, index) => {
		if (!item) {
			return;
		}

		if (item.type && item.type !== 'message') {
			const token = buildDetailToken(item, index === output.length - 1);
			if (token) {
				displayItems.push({
					type: 'detail',
					id: item.id ?? `detail-${index}`,
					token
				});
			}
			return;
		}

		if (item.type === 'message') {
			const text = getMessageText(item);
			if (text.trim()) {
				displayItems.push({
					type: 'message',
					id: item.id ?? `message-${index}`,
					text
				});
			}
			return;
		}

		const fallbackText = getMessageText(item);
		if (fallbackText.trim()) {
			displayItems.push({
				type: 'message',
				id: item.id ?? `output-${index}`,
				text: fallbackText
			});
		}
	});

	return displayItems;
}

export function getOutputText(output?: OutputItem[] | null): string {
	return (output ?? [])
		.filter((item) => item?.type === 'message')
		.map(getMessageText)
		.filter((text) => text.trim())
		.join('\n');
}

function appendDelta(current: unknown, delta: unknown): unknown {
	if (typeof current === 'string' || typeof delta === 'string') {
		return `${current ?? ''}${delta ?? ''}`;
	}
	if (
		current &&
		delta &&
		typeof current === 'object' &&
		typeof delta === 'object' &&
		!Array.isArray(current) &&
		!Array.isArray(delta)
	) {
		return { ...(current as Record<string, unknown>), ...(delta as Record<string, unknown>) };
	}
	return delta ?? current ?? '';
}

function ensureOutputItem(
	output: OutputItem[],
	outputIndex: number,
	fallback?: OutputItem
): OutputItem {
	while (output.length <= outputIndex) {
		// Only the addressed slot gets the event's item; filler slots must not reuse its id.
		const item =
			output.length === outputIndex && fallback
				? { ...fallback }
				: { type: 'message', status: 'in_progress', role: 'assistant', content: [] };
		output.push(item);
	}
	output[outputIndex] = { ...output[outputIndex] };
	return output[outputIndex];
}

function ensurePart(parts: OutputContentPart[], index: number, fallback?: OutputContentPart) {
	while (parts.length <= index) {
		parts.push(fallback ?? { type: 'output_text', text: '' });
	}
	parts[index] = { ...parts[index] };
	return parts[index];
}

function setPart(
	parts: OutputContentPart[],
	index: number,
	part: OutputContentPart,
	fallback?: OutputContentPart
): void {
	// Assigning past the end leaves a hole that later spreads turn into undefined parts.
	ensurePart(parts, index, fallback);
	parts[index] = part;
}

function findOutputItemIndex(output: OutputItem[], item: OutputItem): number {
	return output.findIndex((existing) => !!item.id && existing?.id === item.id);
}

function responseEventUpdatesOutputItem(eventType: string): boolean {
	return (
		eventType === 'response.content_part.added' ||
		eventType === 'response.reasoning_summary_part.added' ||
		eventType.endsWith('.delta') ||
		eventType.endsWith('.done')
	);
}

export function applyResponseStreamEvent(
	output: OutputItem[] = [],
	event: ResponseStreamEvent
): OutputItem[] {
	const eventType = event?.type ?? '';
	if (!eventType.startsWith('response.')) {
		return output;
	}

	if (eventType === 'response.completed') {
		return event.response?.output ? [...event.response.output] : output;
	}

	const nextOutput = [...output];
	const eventItemIndex = event.item_id
		? nextOutput.findIndex((item) => item?.id === event.item_id)
		: -1;
	const outputIndex =
		eventItemIndex >= 0 ? eventItemIndex : (event.output_index ?? Math.max(output.length - 1, 0));

	if (eventType === 'response.output_item.added') {
		if (!event.item) {
			return output;
		}
		const item = { ...event.item };
		const existingIndex = findOutputItemIndex(nextOutput, item);
		if (existingIndex >= 0) {
			nextOutput[existingIndex] = item;
		} else if (outputIndex < nextOutput.length) {
			nextOutput.splice(outputIndex, 0, item);
		} else {
			nextOutput.push(item);
		}
		return nextOutput;
	}

	if (eventType === 'response.output_item.done') {
		if (!event.item) {
			return output;
		}
		const item = { ...event.item };
		const existingIndex = findOutputItemIndex(nextOutput, item);
		if (existingIndex >= 0) {
			nextOutput[existingIndex] = item;
		} else if (outputIndex < nextOutput.length) {
			nextOutput[outputIndex] = item;
		} else {
			nextOutput.push(item);
		}
		return nextOutput;
	}

	if (!responseEventUpdatesOutputItem(eventType)) {
		return output;
	}

	const item = ensureOutputItem(nextOutput, outputIndex, {
		id: event.item_id,
		type: eventType.includes('reasoning') ? 'reasoning' : 'message',
		status: 'in_progress',
		role: 'assistant',
		content: []
	});

	if (eventType === 'response.content_part.added') {
		if (item.type === 'reasoning' || !event.part) {
			return nextOutput;
		}
		item.content = [...(item.content ?? [])];
		setPart(item.content, event.content_index ?? item.content.length, { ...event.part });
		return nextOutput;
	}

	if (eventType === 'response.reasoning_summary_part.added') {
		if (!event.part) {
			return nextOutput;
		}
		item.summary = [...(item.summary ?? [])];
		const summaryIndex = event.summary_index ?? item.summary.length;
		setPart(item.summary, summaryIndex, { ...event.part }, { type: 'summary_text', text: '' });
		return nextOutput;
	}

	if (eventType.endsWith('.delta')) {
		const deltaType = eventType.split('.')[1];

		if (deltaType === 'reasoning_summary_text') {
			const summaryIndex = event.summary_index ?? 0;
			item.summary = [...(item.summary ?? [])];
			const part = ensurePart(item.summary, summaryIndex, { type: 'summary_text', text: '' });
			part.text = appendDelta(part.text ?? '', event.delta);
			return nextOutput;
		}

		const key = deltaType === 'output_text' || deltaType === 'reasoning_text' ? 'text' : deltaType;
		item.content = [...(item.content ?? [])];
		const part = ensurePart(item.content, event.content_index ?? 0);
		part[key] = appendDelta(part[key], event.delta);
		return nextOutput;
	}

	if (eventType.endsWith('.done')) {
		const typeName = eventType.split('.')[1];
		if (typeName === 'content_part' && event.part) {
			item.content = [...(item.content ?? [])];
			const contentIndex = event.content_index ?? Math.max(item.content.length - 1, 0);
			setPart(item.content, contentIndex, { ...event.part });
		} else if (
			(typeName === 'output_text' || typeName === 'text' || typeName === 'reasoning_text') &&
			event.text !== undefined
		) {
			item.content = [...(item.content ?? [])];
			const part = ensurePart(item.content, event.content_index ?? 0);
			part.text = event.text;
		}
	}

	return nextOutput;
}

export function replaceOutputMessageText(
	output: OutputItem[] = [],
	oldContent: string,
	newContent: string
): OutputItem[] {
	if (!oldContent) {
		return output;
	}

	let replaced = false;
	const nextOutput = output.map((item) => {
		if (replaced || item?.type !== 'message' || !Array.isArray(item.content)) {
			return item;
		}

		const partIndex = item.content.findIndex(
			(part) => typeof part?.text === 'string' && part.text.includes(oldContent)
		);
		if (partIndex === -1) {
			return item;
		}

		replaced = true;
		const nextContent = [...item.content];
		const part = nextContent[partIndex];
		nextContent[partIndex] = {
			...part,
			text: (part.text as string).replace(oldContent, newContent)
		};

		return {
			...item,
			content: nextContent
		};
	});

	return replaced ? nextOutput : output;
}
