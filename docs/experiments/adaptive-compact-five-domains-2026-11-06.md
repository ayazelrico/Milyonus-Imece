# Ortak kısa CLI talimatıyla uyarlanan üretim

Sonuç: iki kolda da **5/5 doğrulanmış kabul**, sıfır gözlenen yanlış kabul ve
150'şer tamamlanmış çağrı. Baseline 958.593, aday 957.583 token kullandı.
Gözlenen azalma yalnızca **%0,105**; bu yapı yarı token hedefini sağlamadı.
Bu küçük fark istatistiksel anlamlılık veya üretim kazancı kanıtı değildir.

6 Kasım 2026'da hazırlanan eşleşmiş örneklem, `adaptive_production` ayarını
diğer yürütme ayarlarından ayırır. Baseline ve aday aynı kısa CLI talimatını
kullanır; talimat profili bu deneyde değişen faktör değildir. Kaynak sürümü
`9a7fcd7`; iki manifest aynı implementation hash ve protokolü taşır.

Önceden seçilen görevler: `stable_unique`, `fix_binary_search`, `group_totals`,
`left_join`, `evidence_votes`. Her alandaki ilk görev bir kez çalıştırılır.
İki kolda da 17 ajan, tek eşzamanlı gönderim, en fazla dört tur, görev başına
500.000 tamamlanmış token üzerinden yumuşak sınır ve kol başına 200 gerçek
CLI çağrısı tavanı vardır. Model her koltukta `gpt-6.1-sol`; backend aynı
digest ile sabitlenmiş Docker imajıdır. Ham sağlayıcı API'si kullanılmaz.

Değişen tek konfigürasyon faktörü uyarlama bayrağıdır; bu bayrak üretim
genişliğini, hedefli onarımı, konsey bağlamını ve durgunluk davranışını birlikte
etkileyebilir. Sonuç tek bir alt mekanizmaya atfedilemez. 17 ajanlık yapıdaki
üretim tabanı zaten küçüktür; bu örneklem 120 ajanlık ölçeğin temsilcisi değildir.

Hazırlık model çağrısı yapmadı. Ardından her iki kol da beş görevi tamamladı;
tamamlanmamış/belirsiz çağrı bulunmadı. Bildirilen token toplamları gerçek
çağrı kayıtlarıyla eşleşiyor. USD kullanımı ise hâlâ bilinmiyor.

| Görev | Baseline token | Aday token | İki kolun sonucu |
| --- | ---: | ---: | --- |
| stable_unique | 188.844 | 187.977 | doğrulanmış kabul |
| fix_binary_search | 197.035 | 194.499 | doğrulanmış kabul |
| group_totals | 188.759 | 189.342 | doğrulanmış kabul |
| left_join | 192.760 | 192.862 | doğrulanmış kabul |
| evidence_votes | 191.195 | 192.903 | doğrulanmış kabul |

Tüm görevler iki kolda da ilk turda, iki üreticiyle tamamlandı; çağrı sayısı
azalmadı. Dolayısıyla bu koşular üretici genişliği azaltmasının veya hedefli
onarımın faydasını göstermiyor. Bayrağı açmanın bu küçük ajan düzeninde
kendiliğinden iki kat token verimi sağlamadığı gözlendi. 120 ajanlık ölçekteki
etki ayrıca ölçülmelidir; bu örneklemden o ölçeğe oran taşınmaz.

Resmi karşılaştırmada `token_cost_at_most_half=false`, `accepted_5x=false`.
İç kapıların ürettiği kontroller aynı kanıt kimliklerini taşımadığından eşleşen
kapı iş yükü sayısı sıfırdır; %60 doğrulama azalması da çıkarılamaz. Dış oracle
ve protokol iki kolda sabittir. `left_join` bu koşuda geçti; önceki deneyin
belirsiz çağrıları bununla uzlaştırılmış sayılmaz veya tekrar gönderilmez.

Çağrı başına USD dökümü yoktur. Bilinmeyen kullanım sıfır sayılmaz; başarısız
veya bütçede duran görevler karşılaştırmadan çıkarılmaz. Model bağımsızlığı ve
bağımsız insan denetçisi kanıtı ayrıca eksiktir. Beş görev × bir tekrar, gerekli
50 × 5 matrisi sağlamaz. Önceki farklı kaynak/protokollerdeki oranlar bu
deneyle çarpılarak toplam kazanç hesaplanmaz.

Ham kayıtlar: `experiments/adaptive-compact-five-domains-2026-11-06/`.
`comparison.json` resmi kapı sonucudur; `observation.json` toplamları, blok
başına çağrı/tokenları, üretim planlarını ve rapor SHA-256 özetlerini içerir.
Tamamlanma anında kaynak ve CLI dosyası özetleri manifestle tekrar eşleştirildi.
Bu yerel tutarlılık kontrolü sağlayıcı model sürümünün veya insan denetiminin
imzalı beyanı değildir.
