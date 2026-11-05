# Kısa CLI talimat profili — 5 Kasım 2026

Bu kayıt bir görevlik kalibrasyondur; 5X kabulü veya üretim genellemesi değildir.

## Ön tanı

Aynı `READY` isteğine normal profil 9349/9347, kısa profil 5316/5314 token
bildirdi. İkişer çağrılık tanı giriş yükünde yaklaşık yüzde 43 azalma gösterdi.
Ham kayıt: `experiments/compact-cli-preflight-2026-11-05.json`.

## Dondurulmuş görev kalibrasyonu

`core-v2 / stable_unique`, bir tekrar, seed 0, 17 ajan, aynı model ve sabit
Docker imajı kullanıldı. Her iki kol için koşu başına token sınırı önceden
500.000, çağrı sınırı 80 olarak kaydedildi. İki çekirdek yapılandırma da
`docs/imece-codex-baseline.toml` idi. Yalnızca adayın yerleşik CLI talimatları
kısa metin profiliyle değiştirildi. Önceki kampanyaların 250.000 token sınırı
ve bütçede duran sonuçları değiştirilmedi; bu ayrı deneydir.

| Ölçü | Normal profil | Kısa profil |
| --- | ---: | ---: |
| Gerçek CLI çağrısı | 30 | 30 |
| Toplam token | 312561 | 188973 |
| Süre, saniye | 324.706 | 344.956 |
| Nihai kabul | 1 | 1 |
| Gizli dış referansı geçen kabul | 1 | 1 |
| Gözlenen yanlış kabul | 0 | 0 |
| USD bedeli | bilinmiyor | bilinmiyor |

Bu tek görevde doğrulanmış sonuç başına token oranı 0.6046; azalma yaklaşık
%39,5. Kısa profil bu ölçümde yaklaşık %6,2 daha yavaştı. Tokenların yarıya
inmesi P3 hedefi bu örnekte sağlanmadı. Adayda altı üretilmiş kontrol hatası
raporlandı; bunların çağrı giderleri ve sonraki yeniden testler toplamda
bırakıldı. İki taraftaki kontrol iş yükleri aynı olmadığı için P2 önbellek
azalması hesaplanmadı.

Ham raporlar `experiments/compact-calibration-2026-11-05/` altındadır.
`comparison-reviewed.json`, değişen tek etkeni `cli_prompt` olarak gösterir.
`accepted_5x=false`: 50×5 matris, çağrı bazında gerçek faturalar, model kökeni
bağımsızlığı ve bağımsız nihai denetim yoktur. Tek başarının Wilson aralığı
çok geniştir; kalibrasyon genel başarı oranı veya hızlanma kanıtı değildir.

## İnceleme ve yerel doğrulama

Ayrı GPT-6-Sol oturumu, aynı Seatbelt engeli ve JSONL ayrıştırıcısının
korunduğunu, talimat özetinin manifest/yeniden başlatma kimliğine girdiğini
inceledi. Çoklu ayar değişikliklerinden tek etkiye sonuç çıkarılmaması
uyarısı üzerine hazırlık ve karşılaştırma raporlarına etken sınıflandırması
eklendi. İnceleme insan veya farklı sağlayıcı sertifikası değildir.
Rapor: `docs/audits/2026-11-05-compact-profile-review.md`.

Dosya yaşam döngüsü ve hata temizliği dahil regresyonlardan sonra Docker
etkin tam yerel test koşusu: **486 geçti, atlanan test yok**. Ruff, biçim ve
workflow kontrolleri geçti. Profil varsayılan olarak kapalı kalır.
