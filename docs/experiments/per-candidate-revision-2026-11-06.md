# Aday bazında revizyon kalibrasyonu

Önceki `group_totals` koşusunda bir aday temiz eleştiri aldı, diğerine
tek geçişli toplama önerildi. O sürüm iki adayı da revize etti. `e7b8c96`
commit'inde karar aday bazına taşındı. Kapıda bulgusu olan adayın yazarı
bulguyu da görür. Bir adayın atlanan çağrısı, diğer adayın revizyonuna engel
olmaz. İkisi de aynı yeniden test aşamasından geçer.

Bu takipte `group_totals` için önceden hazırlanmış tek eşleşmiş tekrar
vardır. Her iki kolda uyarlanan üretim, kısa CLI talimatı, 17 ajan,
`gpt-6.1-sol`, aynı gizli oracle ve aynı digest ile sabitlenmiş Docker imajı
kullanılır. Değişen ayar `skip_clean_revision`. Sınırlar görev başına
500.000 tamamlanmış token ve kol başına 60 CLI çağrısıdır. Görev, önceki
karma eleştiri gözlemi nedeniyle seçildi. Bu seçim üretim dağılımını temsil
eden bir örneklem sağlamaz.

| `group_totals` | Baseline | Aday |
| --- | ---: | ---: |
| Doğrulanmış kabul | 1/1 | 1/1 |
| Tamamlanan CLI çağrısı | 30 | 29 |
| Toplam token | 189.060 | 182.014 |
| Çapraz eleştiri tokenı | 12.160 | 12.784 |
| Revizyon çağrısı | 2 | 1 |
| Revizyon tokenı | 13.662 | 6.796 |

Tek geçişli çözümün eleştirisi değişiklik istemedi. Sıralama kullanan çözümün
eleştirisi tek geçişli yönteme geçmeyi önerdi. Yalnızca ikinci aday revize
edildi. Aday kolun toplam token kullanımı %3,73 daha düşük. Ek eleştiri
bağlamı toplam hesaba dahil. İki kolun da kullanım kayıtları tam ve toplamları
transkriptle eşleşiyor. Bu tek görev ve tek tekrar üzerinden üretim kazanımı
tahmin edilmedi. USD maliyeti bilinmiyor ve `accepted_5x=false`.

Ham raporlar `experiments/per-candidate-revision-2026-11-06/` altında.
