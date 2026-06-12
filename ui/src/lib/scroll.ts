export interface ScrollContainer {
	scrollTop: number;
	scrollHeight: number;
}

export function scrollToBottom(container: ScrollContainer): void {
	container.scrollTop = container.scrollHeight;
}
