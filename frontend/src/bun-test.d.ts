declare module 'bun:test' {
	type TestCallback = () => void | Promise<void>;
	type TestRegistrar = (name: string, callback: TestCallback) => void;

	interface Matchers {
		toBe(expected: unknown): void;
		toBeNull(): void;
		toContain(expected: unknown): void;
		toEqual(expected: unknown): void;
		toHaveLength(expected: number): void;
	}

	export const describe: TestRegistrar;
	export const test: TestRegistrar;
	export function expect(actual: unknown): Matchers;
}
