// Job-Status-Polling mit Cancellation.
//
// Ein laufender Poll kann per Token abgebrochen werden: startet der Nutzer
// einen zweiten Ingest, während der erste noch pollt, cancelt der Submit-
// Handler das alte Token, damit nicht zwei Polls denselben Status-Sink
// (DOM-Elemente) überschreiben. Der Sink ist injizierbar, damit poll ohne
// DOM testbar ist.

export function makeToken() {
  return { cancelled: false };
}

// poll läuft, bis der Job 'done'/'failed' ist, das Token gecancelt wird oder
// maxTries erreicht sind. Schreibt ausschließlich über den sink.
export async function poll({
  vault,
  jobId,
  fetchJob,
  sink,
  token,
  maxTries = 40,
  intervalMs = 3000,
}) {
  for (let i = 0; i < maxTries; i++) {
    await new Promise((r) => setTimeout(r, intervalMs));
    if (token.cancelled) return;
    let job;
    try {
      job = await fetchJob(vault, jobId);
    } catch (e) {
      if (token.cancelled) return;
      sink.show(`Job #${jobId}: Statusabfrage fehlgeschlagen — ${e.message}`, 'error');
      continue;
    }
    if (token.cancelled) return;
    if (job.status === 'done') {
      sink.setStep('done');
      sink.show(`Job #${jobId}: fertig ✓`, 'ok');
      return;
    }
    if (job.status === 'failed') {
      sink.setStep('failed');
      sink.show(`Job #${jobId}: fehlgeschlagen — ${job.error || 'unbekannter Fehler'}`, 'error');
      return;
    }
    sink.setStep('running');
    sink.show(`Job #${jobId}: ${job.status}…`);
  }
  sink.show(`Job #${jobId}: Zeitlimit erreicht — Status später prüfen.`, 'error');
}
