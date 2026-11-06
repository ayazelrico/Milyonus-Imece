# Docker çalışma kimliği ve politika değişimi

6 Kasım 2026 devamında kanıt kimliği, gerçekten seçilen imajın kimliği/OS/mimarisi
ve Docker daemon'unun kimliği/OS/mimarisi/kernel/sürüm/güvenlik özelliklerine
bağlandı. Yalnızca ana makinenin mimarisini ve imaj referansını bilmek, başka
Docker bağlamındaki yürütmeyi ayırt etmek için yeterli değildi.

Kaynak dosyasının özeti yanında yürütme komutunun geçici dizin ve konteyner
ismi sabitlenmiş hali de kimliğe girer. Böylece aynı yürütücü kaynağını miras
alan bir sınıf PID sınırını değiştirirse eski kanıtı kullanamaz. Probe'da PID
sınırı gerçekten 32'den 16'ya düşürülerek bu yol Docker içinde çalıştırıldı.
Diğer ağ ve dosya izolasyon kuralları bu deneyde değişmedi.

Her sabit digest'li Docker çalışmasında imaj ve daemon için iki metadata
sorgusu yapılır. Yalnızca seçilmiş alanlar okunur; tam Docker yapılandırması,
proxy veya kimlik bilgileri kayda alınmaz. Okuyucuların çıktısı ve süresi
sınırlıdır; iptal veya taşmada alt süreç sonlandırılıp beklenir. Metadata
eksik/bozuksa önceki kanıt kullanılamaz ve yeni başarı önbelleğe yazılmaz.
Yürütme yine denenebilir. Ortam doğrulanamazken Docker'ın çıkış kodu 1 ile
verdiği hata, kesin çözüm kusuru sayılmaz (`docker_runtime_unverified`).

Üç açık deterministik örnek, beş tekrar, soğuk önbellek ve operatörün açık
kanıt izinleriyle yeniden ölçüldü:

| Süreç kapsamı | Önbelleksiz | Önbellekli | Azalma |
| --- | ---: | ---: | ---: |
| Doğrulama konteyneri | 15 | 3 | %80 |
| İmaj/daemon metadata CLI çağrısı | 30 | 30 | %0 |
| Toplam Docker CLI süreci | 45 | 33 | %26,7 |

%80 yalnızca doğrulama konteynerleri içindir. Ek kimlik sorguları dahil tüm
CLI süreçlerinde ölçülen azalma %26,7'dir; süre veya dolar tasarrufu ölçülmedi.
Kaynak, oracle, timeout ve daha sıkı PID politikası değişince yeniden yürütme,
değişmiş kimliğin tekrarında yeniden kullanım doğrulandı. Onaysız ve başarısız
kontroller yeniden çalıştı. Ayrı gerçek Docker regresyonunda sıcak kanıttan
sonra bulunamayan bir Docker bağlamına geçildi; eski başarı kullanılmadı.

Birim testleri ayrıca seçilen imaj, OS, mimari, daemon, kernel, sürüm,
güvenlik özellikleri, kaynak özeti ve komut değişimlerini kapsar. Bunlar farklı
sağlıklı daemon veya imajlarla yapılan gerçek karşılaştırmalar değildir.
Yetkili bir operatörün sorgu ile yürütme arasında daemon yapılandırmasını
değiştirmesine karşı atomik bir ortam kilidi veya donanım doğrulaması yoktur.

Eski önbellek dosyası korunur, fakat yeni kimlikler eski onay listesiyle
eşleşmez. İncelenmiş deterministik kontroller için izinlerin yeni ortamda
yeniden üretilmesi gerekir; eski hash'ler elle yeni hash'lere çevrilmez.

Ham kayıt: `experiments/cache-runtime-probe-2026-11-06.json`.
Kaynak özetleri bu raporda yer alır. Model çağrısı yapılmadı.
Bu sentetik yük üretimde tekrar oranını, tam 50 × 5 matriste P2 kabulünü veya
5X kazancı kanıtlamaz; `accepted_5x=false` korunur.
