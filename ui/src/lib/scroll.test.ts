import { describe, expect, it } from "vitest";
import { scrollToBottom } from "./scroll";

describe("scrollToBottom", () => {
	it("sets scrollTop to current scrollHeight", () => {
		const container = { scrollTop: 0, scrollHeight: 1234 };

		scrollToBottom(container);

		expect(container.scrollTop).toBe(1234);
	});
});
