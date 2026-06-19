import { test } from 'node:test';
import assert from 'node:assert';
import { poll, makeToken } from '../src/lib/poll.js';

function makeSink() {
  const calls = [];
  return {
    calls,
    show(text, cls) { this.calls.push(['show', text, cls]); },
    setStep(step) { this.calls.push(['setStep', step]); },
  };
}

const tick = (ms = 1) => new Promise((r) => setTimeout(r, ms));

test('done job writes done/ok and stops', async () => {
  const sink = makeSink();
  await poll({
    vault: 'v', jobId: 7, token: makeToken(), sink,
    fetchJob: async () => ({ status: 'done' }),
    maxTries: 3, intervalMs: 1,
  });
  assert.ok(sink.calls.some((c) => c[0] === 'setStep' && c[1] === 'done'));
  assert.ok(sink.calls.some((c) => c[0] === 'show' && c[1].includes('fertig')));
});

test('failed job writes failed/error', async () => {
  const sink = makeSink();
  await poll({
    vault: 'v', jobId: 8, token: makeToken(), sink,
    fetchJob: async () => ({ status: 'failed', error: 'boom' }),
    maxTries: 3, intervalMs: 1,
  });
  assert.ok(sink.calls.some((c) => c[0] === 'setStep' && c[1] === 'failed'));
  assert.ok(sink.calls.some((c) => c[0] === 'show' && c[1].includes('boom')));
});

test('a token cancelled before the first write writes nothing', async () => {
  const sink = makeSink();
  const token = makeToken();
  token.cancelled = true;
  await poll({
    vault: 'v', jobId: 1, token, sink,
    fetchJob: async () => ({ status: 'running' }),
    maxTries: 5, intervalMs: 1,
  });
  assert.equal(sink.calls.length, 0);
});

test('a token cancelled mid-run stops further sink writes', async () => {
  // 1. Iteration schreibt 'running'; beim 2. fetchJob wird gecancelt — danach
  // darf kein weiterer write passieren (genau eine setStep('running')).
  const sink = makeSink();
  const token = makeToken();
  let fetches = 0;
  await poll({
    vault: 'v', jobId: 1, token, sink,
    fetchJob: async () => {
      fetches += 1;
      if (fetches === 2) token.cancelled = true;
      return { status: 'running' };
    },
    maxTries: 10, intervalMs: 1,
  });
  const setSteps = sink.calls.filter((c) => c[0] === 'setStep');
  assert.equal(setSteps.length, 1);
  assert.equal(setSteps[0][1], 'running');
});

test('a second poll cancels the first so it no longer wins the sink', async () => {
  // Simuliert zwei Submit-Handler: B cancelt A, B schafft 'done', A dürfte
  // danach nichts mehr schreiben (self-contained ohne echtes Multi-Task-Racing).
  const sinkA = makeSink();
  const sinkB = makeSink();
  const tokenA = makeToken();
  const tokenB = makeToken();
  const fetchJob = async (_v, jobId) => (jobId === 1 ? { status: 'running' } : { status: 'done' });

  // A startet, läuft eine Iteration (schreibt 'running'), dann übernimmt B.
  const pA = poll({ vault: 'v', jobId: 1, token: tokenA, sink: sinkA, fetchJob, maxTries: 20, intervalMs: 1 });
  await tick(2);
  tokenA.cancelled = true; // B nimmt über
  const pB = poll({ vault: 'v', jobId: 2, token: tokenB, sink: sinkB, fetchJob, maxTries: 20, intervalMs: 1 });
  await Promise.all([pA, pB]);

  // B erreicht 'done'; A hat nach dem Cancel nichts mehr geschrieben (kein 'done').
  assert.ok(sinkB.calls.some((c) => c[0] === 'setStep' && c[1] === 'done'));
  assert.ok(!sinkA.calls.some((c) => c[0] === 'setStep' && c[1] === 'done'));
});
