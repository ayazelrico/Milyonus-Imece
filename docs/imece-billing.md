# CLI giderlerini deney raporuyla eşleştirme

Deney çalıştırıcısı her gerçek CLI denemesinden önce çağrı kimliğini (`call_id`), görev adını ve tekrar numarasını kaydeder. Aynı günlükten okunan eski yanıt için yeni çağrı kimliği üretilmez.

Sağlayıcı gerçek USD tutarını her çağrıya bağlayan bir döküm sağlıyorsa, operatör aşağıdaki alanları içeren bir JSON dosyası hazırlayabilir. `report_hash`, rapor nesnesinin `evals.imece.protocol.digest` ile hesaplanan özetidir. `total_usd` bu deneye ait satırların dökümdeki toplamıdır. Her satırın döküm içindeki referansı benzersiz olmalıdır.

```json
{
  "report_hash": "<rapor özeti>",
  "currency": "USD",
  "statement_reference": "<döküm kimliği>",
  "total_usd": "0.015",
  "charges": [
    {"call_id": "<çağrı kimliği>", "line_reference": "<satır kimliği>", "usd": "0.015"}
  ]
}
```

```sh
uv run python -m evals.imece.billing run.json receipts.json --out reconciled.json
```

Komut, tamamlanmış deneyde başarısızlar dahil tüm çağrılar için bire bir eşleşme arar, ondalık tutarları toplar ve görev başına giderleri ayrı bir dosyaya yazar. Dökümün gerçekliğini ve hangi hesaba ait olduğunu bağımsız denetçi kontrol eder. Çağrı başına ücret sağlamayan aboneliklerde maliyet bilinmiyor olarak kalır. Bu çıktı, harcama öncesinde bütçe ayrıldığını veya denetimin tamamlandığını belgelemez.

Hazırlık aşamasında `--max-cli-calls N` ile tüm deney için bir çağrı sayısı sınırı koyulabilir. Çağrı başlamadan önce deneme kaydedilir. Başarısız ve yarıda kesilmiş denemeler de bu sınırdan düşer. Günlükten tekrar okuma yeni çağrı harcamaz. `--declared-budget-usd TUTAR`, faturalar geldiğinde kıyaslanacak parasal tavanı deney kimliğine ekler. CLI anlık çağrı fiyatı bildirmediği için bu parasal tavan harcama anında uygulanmaz.

İki sürüme ait gerçek dökümler varsa, `evals.imece.compare` komutuna `--baseline-receipts` ve `--candidate-receipts` ile ham döküm JSON dosyalarını verin. Denetçi, denetim kaydındaki `baseline_receipts_hash` ve `candidate_receipts_hash` alanlarıyla incelediği dökümleri bağlar. Araç maliyeti bütün görevlerden hesaplar. Hazırlıkta kaydedilen parasal tavan veya faturanın denetçi onayı eksikse 5X kabulü açık kalır. Ham deney raporları korunur.

## Tahmini maliyet ve kabul

Sayısal toplamın bulunması tek başına P5 için yeterli değildir. İki rapordan
birinin maliyeti tahmini olarak işaretliyse `accepted_5x` reddedilir. Ham
raporda tahmin işareti eksikse de doğrulanmış fatura varsayılmaz. CLI için
tam çağrı dökümünü kapsayan harici makbuz eşleştirmesi, hesaplamada maliyetleri
doğrulanmış olarak kullanır; kaynak raporu değiştirmez. Bağımsız denetçinin
rapor ve makbuz özetlerini onaylaması ayrıca gereklidir.
