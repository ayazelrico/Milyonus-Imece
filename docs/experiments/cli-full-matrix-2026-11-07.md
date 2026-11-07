# 500 koşuluk Codex CLI kıyaslaması

Durum: **29/500 kayıtla kapatılan olumsuz ön deney.** 471 satır
çalıştırılmadı. Aday `fix_even_median` koşusunda görünür sözleşme ile
oracle'ın JSON arayüzü uyuşmadı. Bu matris 5X kabul kanıtı olarak
tamamlanmayacak; eski kayıtlar değiştirilmeyecek. Yeni deney ayrı protokol
ve ayrı checkpoint dizini kullanmalıdır.

7 Kasım 2026’da `core-v2` veri kümesindeki 50 görev için beşer tekrar iki
kolda donduruldu. Her kol 250 satır içerir. Kontrol standart CLI talimatı ve
sabit üretim, aday kısa talimat ve uyarlanan üretim kullanır. Ölçüm bu iki
değişikliğin birleşik etkisini kapsar. İki kol aynı model, 17 ajan, Docker
ortam kimliği, dış oracle ve görev sırasıyla çalışır. Yumuşak token sınırı
görev başına 500.000, kalıcı CLI çağrı tavanı kol başına 12.500’dür.

Çağrı bazında ücret dökümü bulunmadığı için USD alanları bilinmiyor olarak
kalır. Tam matris tamamlandığında bile USD ve bağımsız denetim şartları ayrıca
karşılanmalıdır. Bu çalışma abonelikli Codex CLI oturumunu kullanır.

Checkpoint’ler `experiments/cli-full-matrix-2026-11-07/` altında.
İki kolun toplu durumu `uv run python scripts/imece_matrix_status.py
experiments/cli-full-matrix-2026-11-07` komutuyla okunur. Çıktı toplam kalan
satırları, tamamlanan eşleşmeleri ve her kolun sıradaki görevini gösterir.
İlerleme `uv run python -m evals.imece.inspect_run` komutuna ilgili JSON
dosyası verilerek okunabilir. `--max-new-trials` değeri bir sonraki oturumda
değiştirilebilir. Tamamlanan satırlar tekrar gönderilmez. Ortam ve kaynak
özetleri her devamda eşleşmelidir. Bekleyen işlem için `.calls/` ve `.journal/`
dizinleri aynı makinede korunmalıdır.

İlk görev `stable_unique` iki kolda da dış doğrulamadan geçti. Kontrol
311.706 token ve 30 çağrı, aday 182.755 token ve 29 çağrı kullandı.
Bu satırlar tam matrisin parçasıdır. Güncel kalan sayı checkpoint’lerden okunur.

İkinci görev `runs` da iki kolda doğrulandı. Kontrol 314.961, aday 177.298
token kullandı. Üçüncü görev `rotate` aday kolunda 182.785 token ile
doğrulandı. Toplam beş satır tamamlandı ve belirsiz çağrı oluşmadı. 7 Kasım
sabah oturumu kısa Codex kotası %97’ye ulaştığında görev sınırında kapandı.
Sonraki baseline görevi `rotate`, sonraki aday görevi kendi manifest
sırasındaki dördüncü görevdi. O oturum sonunda 495 satır açıktı.

7 Kasım öğleden sonraki devamda baseline 8, aday 11 satıra ulaştı.
Toplam 19/500 satır kayıtlı ve 481 satır açık. Baseline sekiz görevin
tamamında, aday on görevde dış doğrulamadan geçti. Aday `divisors`
görevindeki bir çağrıda Codex başarısız tur bildirdi. Bu satır `budget`,
kullanım `unknown` olarak korundu. Sonraki aday görevlerine açık
`--continue-after-uncertain-trial` seçeneğiyle geçildi. Belirsiz çağrı
yeniden gönderilmedi. Adayın tam token ve dolar maliyeti bu nedenle
hesaplanamıyor. Sonraki görevler baseline için `transpose`, aday için
`fix_chunk_tail`. Kısa kullanım penceresi son kontrolde %99 doluydu.

Kota yenilendikten sonraki beşer koşuluk partiyle baseline 13, aday 16
satıra ulaştı. Baseline 13/13 dış doğrulama, aday 14/16 dış doğrulama
sağladı. Adayda önceki belirsiz çağrı ve yeni bir yanlış kabul var.
`fix_even_median` matematiksel kesir döndürdü; kamuya açık metinde
belirtilmeyen JSON taşıma şartını sağlayamadı. Bu bulgu üzerine yeni
parti başlatılmadı. [Bulgu analizi](../audits/2026-11-07-oracle-interface.md).

Arşivlenen çalışmanın her kol için devam komutu aşağıdaki ortak ayarları
kullanıyordu; bu kayıt komutun yeniden çalıştırılması önerisi değildir. Aday kolunda
config `docs/imece-codex-adaptive.toml`, çıktı `candidate.json` olur ve
`--compact-cli-instructions --continue-after-uncertain-trial` eklenir.
İkinci seçenek yalnızca diğer görevlerin devamına izin verir; kayıtlı
belirsiz `divisors` çağrısını yeniden göndermez. Bu makinede önce
`colima start imece-tests --activate=false` ile ayrılmış ortam açılır.
`TMPDIR` bind mount için paylaşılan dizini, `DOCKER_CONTEXT` dondurulan
daemon'ı seçer; varsayılan Docker bağlamı değiştirilmez.

```sh
TMPDIR=/Users/ayazelrico/.cache/imece-docker-tests \
DOCKER_CONTEXT=colima-imece-tests \
uv run python -m evals.imece.run --engine codex --model gpt-6.1-sol \
  --suite core-v2 --repeats 5 --trial-order repeat-major \
  --max-tokens 500000 --max-cli-calls 12500 --max-new-trials 1 \
  --backend docker --image python@sha256:e695ab189fa2d082b1c61c69a6b888a5adeca61ceeccad107b1ed2a125721a9e \
  --config docs/imece-codex-baseline.toml --resume \
  --out experiments/cli-full-matrix-2026-11-07/baseline.json
```
