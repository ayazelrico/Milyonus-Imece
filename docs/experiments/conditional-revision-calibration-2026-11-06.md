# Koşullu revizyon kalibrasyonu

6 Kasım 2026'da `left_join` görevi, her kolda bir kez çalışacak şekilde
seçildi. Önceki beş alanlı ölçümde bu görevde iki kolun üreticileri kendi
aralarında aynı Python dosyalarını teslim etmişti. Bu seçim koşullu revizyon
yolunu gözlemlemek içindir. Tek görevlik sonuç, görev dağılımını temsil etmez.

İki kol uyarlanan üretimi ve aynı kısa CLI talimatını kullanır. Ortak ayarlar
17 ajan, tek eşzamanlı gönderim, dört tur sınırı, görev başına 500.000 token
yumuşak tavanı, kol başına 60 CLI çağrısı ve `gpt-6.1-sol` modelidir.
Docker imajı digest ile sabittir. `skip_clean_revision` baseline'da kapalı,
adayda açık. Önceden hazırlanan manifestlerde değişen tek ayar budur.
Kaynak commit `fbb1f36`.

Önceki beş alanlı deneyde revizyon yazarları toplam tokenların yaklaşık
%7,3'ünü kullandı. Bu tarihsel pay, koşullu revizyonun ölçülmüş kazancı
değildir. Yeni eleştirmenler diğer adayı ve kapı gözlemlerini de görür.
Karşılaştırma bu ek bağlam dahil bütün gerçek çağrıların kullanımını kapsar.

| `left_join` | Baseline | Aday |
| --- | ---: | ---: |
| Doğrulanmış kabul | 1/1 | 1/1 |
| Toplam CLI çağrısı | 31 | 30 |
| Toplam token | 202.246 | 193.955 |
| Revizyon çağrısı | 2 | 2 |
| Atlanan revizyon çağrısı | 0 | 0 |

İki kol da belirsiz çağrı olmadan tamamlandı. Adayın ilk kapısında kanıt
denetçisi, karmaşıklık iddiasının sabit süreli kimlik karşılaştırması
varsaydığını bildirdi. Düşük önem dereceli bu bulgu normal revizyon yolunu
korudu. Yapılandırılmış çapraz eleştiri çağrısı yapılmadı. Dolayısıyla bu koşu
geri dönüş davranışını gösterir ve token farkı revizyon atlamasına atfedilemez.
Çağrı toplamları transkriptlerle eşleşir. `accepted_5x=false`.
