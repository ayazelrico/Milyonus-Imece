# core-v3 medyan arayüzü kalibrasyonu

7 Kasım 2026, kaynak `379ebad`. Eski deneyde iç onay alıp dış oracle'dan
geçemeyen `fix_even_median` görevi, ayrı v3 sözleşmesiyle iki kolda birer
kez çalıştırıldı. Veri dizini `experiments/cli-v3-interface-2026-11-07/`.
Gizli vakalar ve host scorer aynı kaldı; JSON dönüş arayüzü ve standart
kayan nokta semantiği görünür isteğe eklendi. Eski başarısız satır korunur.

| Kol | İç kabul | Dış oracle | Tur | CLI çağrısı | Token | Saniye |
| --- | --- | --- | --- | --- | --- | --- |
| Kontrol, standart talimat/sabit üretim | Evet | Geçti | 1 | 30 | 318.937 | 339,548 |
| Aday, kısa talimat/uyarlanan üretim | Evet | Geçti | 1 | 28 | 179.603 | 282,733 |

İki rapor `validate_report` ile doğrulandı. Bilinmeyen kullanım veya yanlış
kabul yok. Adayın çift elemanlı medyanı `(a[middle - 1] + a[middle]) / 2`
ile hesapladığı görüldü. Bu sınırlı tekrar, bildirilen arayüzün canlı
model çözümünde kullanıldığını gösterir; neden-sonuç veya genel başarı
garantisi değildir. İki kol kısa talimat ve üretim ayarı bakımından birlikte
farklıdır. Tek görev sonucu 5X, yarı token veya temsili üretim kabulü sağlamaz.

Her koltuk `gpt-6.1-sol`, 17 ajan, en çok dört tur, tek eşzamanlı model
çağrısı; görev token sınırı 500.000 ve kalıcı çağrı tavanı 12.500.
Sabit Docker imajı ve gerçek ortam kimliği iki kolda aynı donduruldu.
Çağrı bazında gerçek USD dökümü bulunmadığı için ücretler bilinmiyor.
Bu kayıt bağımsız denetçi raporu değildir.

Bu iki satır [yeni 500 koşuluk matrise](cli-full-matrix-v3-2026-11-07.md)
dahil edilmez.
