# 500 koşuluk Codex CLI kıyaslaması

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
İlerleme `uv run python -m evals.imece.inspect_run` komutuna ilgili JSON
dosyası verilerek okunabilir. `--max-new-trials` değeri bir sonraki oturumda
değiştirilebilir. Tamamlanan satırlar tekrar gönderilmez. Ortam ve kaynak
özetleri her devamda eşleşmelidir. Bekleyen işlem için `.calls/` ve `.journal/`
dizinleri aynı makinede korunmalıdır.

İlk görev `stable_unique` iki kolda da dış doğrulamadan geçti. Kontrol
311.706 token ve 30 çağrı, aday 182.755 token ve 29 çağrı kullandı.
Bu satırlar tam matrisin parçasıdır. Güncel kalan sayı checkpoint’lerden okunur.

Her kol için devam komutu aşağıdaki ortak ayarları kullanır. Aday kolunda
config `docs/imece-codex-adaptive.toml`, çıktı `candidate.json` olur ve
`--compact-cli-instructions` eklenir.

```sh
uv run python -m evals.imece.run --engine codex --model gpt-6.1-sol \
  --suite core-v2 --repeats 5 --trial-order repeat-major \
  --max-tokens 500000 --max-cli-calls 12500 --max-new-trials 1 \
  --backend docker --image python@sha256:e695ab189fa2d082b1c61c69a6b888a5adeca61ceeccad107b1ed2a125721a9e \
  --config docs/imece-codex-baseline.toml --resume \
  --out experiments/cli-full-matrix-2026-11-07/baseline.json
```
