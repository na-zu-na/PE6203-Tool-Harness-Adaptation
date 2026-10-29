// Official mcp-tasks snapshots dynamically import an absolute package.json path.
// Convert Windows drive paths to file URLs at module resolution time; keep the
// archived server bytes and tool behavior unchanged.
import { registerHooks } from 'node:module';
import { pathToFileURL } from 'node:url';

registerHooks({
  resolve(specifier, context, nextResolve) {
    const esm = Array.from(context.conditions ?? []).includes('import');
    const normalized = esm && /^[A-Za-z]:[\\/]/.test(specifier)
      ? pathToFileURL(specifier).href : specifier;
    return nextResolve(normalized, context);
  },
});
