/**
 * Build-time gate for simulated-caller mode.
 *
 * The mode replaces the borrower's microphone with prerecorded audio. That is a
 * legitimate break-glass fallback when venue acoustics fail, and a dishonest act if
 * an audience is not told. The gate exists so the feature is ABSENT from a normal
 * build rather than merely hidden: `import.meta.env.DEV` alone is insufficient
 * because the venue laptop runs a production preview build.
 *
 * Launch with:  VITE_VACHAN_SIMULATED_CALLER=1 bun run dev
 */
export const SIM_CALLER_ENV = 'VITE_VACHAN_SIMULATED_CALLER';

/** The literal an operator must confirm, and the banner text shown while armed. */
export const SIM_CALLER_LABEL = 'SIMULATED CALLER — PRERECORDED AUDIO';

export function simulatedCallerEnabled(environment: Record<string, string | undefined>): boolean {
	return environment[SIM_CALLER_ENV] === '1';
}
