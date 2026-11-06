# Devam muhasebesi: ayrı Codex incelemesi

6 Kasım 2026: gpt-6-sol, ayrı ve salt okunur Codex CLI oturumu.
Bu bir model kod incelemesidir; bağımsız insan/mali denetim beyanı değildir.
Aşağıdaki bulgular inceleme anındaki satır numaralarını kullanır.

**Findings**

1. **[P1] Resume can dispatch after an unresolved call.** In [run.py](/Users/ayazelrico/Desktop/Milyonus-Imece/evals/imece/run.py:655), `stop_experiment` resets to `False` on every process start. If task A saved a partial row after an unknown CLI call, resuming skips A and can dispatch task B: the admission check at line 609 blocks only A’s trial. Initialize the experiment stop state from unresolved checkpoint calls or rows before starting the next trial.

2. **[P2] Legacy usage is underreported.** In [run.py](/Users/ayazelrico/Desktop/Milyonus-Imece/evals/imece/run.py:543), legacy completed replies have no trial key, so their known tokens appear in `accounting.observed_tokens` but disappear from row and summary `observed_tokens`. A legacy `{"spec", "error"}` call is also omitted from `accounting.unknown_usage_calls` because it has no `state` (line 561). The new legacy resume test checks the accounting total but not the summary. Track unattributed known tokens and unknown calls at experiment level.

**Review limits:** Static, read-only review of the named changes and new tests. I did not run tests or model calls, or read experiments or hidden task oracles. These are code correctness findings, not financial or human certification.

## Bulgulara uygulanan düzeltmeler

1. Başlangıçtaki durdurma durumu artık geçmiş belirsiz çağrılardan kurulur.
   Başka göreve devam açık `--continue-after-uncertain-trial` seçeneği ister;
   aynı belirsiz görev tekrar gönderilmez. `test_imece_budget_scope.py`,
   yeniden başlatmanın çağrı yapmadığını ve açık devamın yalnızca diğer görevi
   çalıştırdığını gerçek koşucu/günlük/checkpoint akışıyla doğrular.
2. Tüm gerçek çağrıların bilinen kullanımı özetin `observed_tokens` alanında
   korunur. Atanamayan kullanım ve belirsiz çağrılar ayrıca raporlanır;
   toplam token veya başarı başına oran uydurulmaz. Eski `spec+error` kayıtları
   da belirsiz kullanım sayacına girer. `test_imece_resume_accounting.py`,
   terk edilen dalı, yeniden kullanılan yanıtı, bütçe engelini ve iki eski
   kayıt biçimini kapsar.

Bu düzeltmeler yerel regresyonlarla doğrulandı; yukarıdaki model oturumu
düzeltmelerin son halini yeniden onaylamış değildir.
