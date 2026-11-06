# Kısa CLI talimatı: beş alanlı eşleşmiş örneklem

5 Kasım'da başlatılan, 6 Kasım 2026'da tamamlanan bu örneklem her alandaki
ilk görevi seçti: kod, hata düzeltme, dönüşüm, entegrasyon ve kanıtlı analiz.
Beş görev × bir tekrar, üretim temsiliyeti veya tam 50 × 5 matrisi değildir.

İki kol aynı 17 ajanlı, uyarlanmayan konfigürasyonu, gpt-6.1-sol modelini,
500.000 token/görev yumuşak sınırını ve 200 çağrı/kol tavanını kullandı.
Tek tedavi farkı adayın kısa CLI talimatıydı. Gizli oracle ve digest ile
sabitlenmiş Docker imajı değişmedi. Kaynak sürümü deneyin
`source-snapshot.json.gz` ve `provenance.json` dosyalarında saklıdır;
sonraki muhasebe düzeltmesi bu canlı koşuların çalıştırdığı sürüm değildir.

| Görev | İki kolun sonucu | Baseline token | Aday token |
| --- | --- | ---: | ---: |
| stable_unique | doğrulanmış kabul | 310.655 | 189.422 |
| fix_binary_search | doğrulanmış kabul | 315.750 | 194.242 |
| group_totals | doğrulanmış kabul | 313.373 | 189.942 |
| left_join | bütçe, oracle geçmedi | bilinmiyor | bilinmiyor |
| evidence_votes | doğrulanmış kabul | 315.321 | 197.218 |

İki kolda da başarı 4/5, gözlenen yanlış kabul sıfırdır. Başarı için Wilson
%95 aralığı her ikisinde de yaklaşık %37,6–%96,4; küçük örneklem geniş bir
belirsizlik taşır. Baseline 132 gerçek çağrı kaydı (131 tamamlanmış), aday
137 kayıt (136 tamamlanmış) içerir. Her kolda `left_join` için bir
`CancelledError` kaydı belirsizdir; bunun ücretinin veya tokenının sıfır olduğu
varsayılmaz. Bilinen token alt sınırları sırasıyla 1.371.076 ve 875.161'dir.
Eksik kullanım nedeniyle bu iki alt sınırdan toplam tasarruf oranı çıkarılmaz.
Başarılı görevler tablosu, başarısız görevin maliyetini dışlayan bir kabul
ölçütü olarak kullanılmaz.

`left_join` satırındaki `budget` durumunun notu belirsiz çağrı nedeniyle yeni
gönderimin engellendiğini söylüyor. O görevdeki bilinen kullanım baseline'da
115.977, adayda 104.337 token; bunlar 500.000 token tavanının aşıldığına kanıt
değildir. Kayıtlı `CancelledError` tek başına iptalin nedenini belirlemez.

İlk dört satırdan sonra süreçler durmuştu. Kullanıcının devam talimatıyla
yalnızca eksik `evidence_votes` çalıştırıldı; belirsiz görev tekrar gönderilmedi.
Bu sırada eski koşucu yeniden başlatmada başka göreve geçişi sessizce
sağlıyordu. Sonraki inceleme bu davranışı buldu; güncel koşucuda varsayılan
devam durur, başka göreve geçmek açık `--continue-after-uncertain-trial`
seçeneği gerektirir. Bu seçenek belirsiz görevi yeniden denemez.

`comparison.json` sonucu **accepted_5x=false**. Tam matris, doğrulanmış USD
makbuzları, model bağımsızlığı kanıtı ve bağımsız denetçi beyanı eksiktir.
Çağrı başına ücret dökümü kullanıcıda mevcut değildir; abonelik veya token
sayısından dolar maliyeti üretilmemiştir. Ayrı Codex incelemesi insan veya
sağlayıcıdan bağımsız bir mali denetim sertifikası değildir.

Raporlar: `experiments/compact-five-domains-2026-11-05/{baseline,candidate,comparison}.json`.
İnceleme: [6 Kasım devam denetimi](../audits/2026-11-06-resume-review.md).
