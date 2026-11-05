# Plan uygulama durumu — 4 Kasım 2026

### Altıncı uygulama turu — görev kimliğine bağlı akış

- SSE bağlantısı `turn_id` ile belirli göreve sabitlendi. Yeniden bağlantı
  sırasında yeni görevin olaylarını eski görevin imleciyle okuma riski kapatıldı.
- Görev/sohbet eşleşmesi sunucuda denetleniyor; eksik veya yabancı görev
  HTTP 404 döndürüyor. Arayüz görev kimliğini bağlantı adresinde taşıyor.
- Regresyon testi aynı sohbette iki görev, farklı sohbet, farklı kullanıcı
  ve bulunamayan görev durumlarını kapsıyor.
- Sağlayıcının SSE hata mesajları artık arayüzde erişilebilir uyarıyla
  gösteriliyor. Mesaj gönderimi reddedilirse taslak geri yükleniyor.
- İlgili web/bağlam/kota testleri: 25 geçti. Python Ruff ve web üretim
  derlemesi geçti. 500 kB paket uyarısı sürüyor. Model çağrısı yapılmadı.
- Planın tümü tamamlanmadı; önceki turlardaki dış kabul ve uygulama
  eksikleri bu değişikliklerle tamamlanmış sayılmıyor.

### Beşinci uygulama turu — proje referansları ve kalıcı sohbet bulma

- Web yürütücüsü kullanıcı çalışma alanındaki bilinen talimat dosyalarını
  tarıyor; yüksek riskli içerik, sembolik bağlantılar, normal dosya olmayan
  girdiler ve 32 KB üstü dosyalar atlanıyor. Sırlar maskeleniyor; XML kaçışı
  ve kaynak etiketleri dahil toplam 8000 karakter sınırı uygulanıyor.
- Tarama sonucu `context.sources` olayıyla arayüzde gösteriliyor.
  `context.compacted` olayı da artık kullanıcıya bilgi veriyor.
- Yeniden başlatma sonrası eski sohbeti bulmak için son 200 sohbeti tarama
  kaldırıldı; kanal, kullanıcı ve başlığa göre doğrudan sorgu eklendi.
  Böylece eski konuşmalar için boş geçmiş veya ikinci çekirdek sohbet oluşması
  önleniyor. 205 yeni sohbetle regresyon testi eklendi.
- İlgili Python testleri: 30 geçti. Ruff ve TypeScript/Vite derlemesi geçti;
  web paket boyutu uyarısı devam ediyor. Gerçek model çağrısı yapılmadı.
- W6 semantik özetleme, proje talimat düzenleyicisi ve uzun konuşma kabulü;
  W7 üretim yük ölçümü; W8 dış beta ve 5X gerçek deneyleri hâlâ açık.

Bu kayıt tamamlanma ilanı değildir. PLAN.md, PLAN-WEB.md ve PLAN-5X.md
hedeflerinin tümü henüz sağlanmamıştır. Önceden var olan yerel değişiklikler
korunmuştur.

## Bu çalışmada uygulananlar

- Web isteklerinde ve görev yürütmede kullanıcı dizinini seçmek için süreç
  genelinde MILYONUS_HOME değiştirme kaldırıldı. Veri tabanı ve görev
  yapılandırma yolları kullanıcıya özel açık parametrelerle seçiliyor.
- Araç onayı sahibinin kimliği denetleniyor. Bir kullanıcının başka
  kullanıcının onayını cevaplaması engelleniyor.
- Görev iptali sohbet kimliğiyle eşleştiriliyor.
- Silinen hesapların eski imzalı oturum çerezleri reddediliyor.
- SSE Last-Event-ID sonrasından devam ediyor; aynı olay tekrar gönderilmiyor.
  Arayüz geçici bağlantı hatasında EventSource yeniden bağlanmasını koruyor.
- Hafıza teyidi gerçek kayıt, etkinlik ve saatlik tekrar sınırı denetimleriyle
  uygulanıyor; kayıt ve denetim zinciri güncelleniyor.
- Kaynak iptali için değişiklik yapmayan, türetilmiş kayıtları da içeren
  önizleme API'si ve arayüzü eklendi. Kaynak açıklaması panelde gösteriliyor.
- Sohbet araması gerçek web sohbet kimliklerini döndürüyor ve arşivlenmiş
  sohbetleri göstermiyor. Arayüzde arama ve durdurma kontrolleri eklendi.
- Web CSS tür bildirimi düzeltildi. Bağımlılık kilidi oluşturuldu; Vite 7 ve
  React eklentisi 5'e geçildi. npm kurulum denetimi sıfır bilinen açık bildirdi.

## Doğrulama ve sınırlar

Yeni regresyonlar kullanıcılar arası onay erişimini, hafıza teyidi sınırını,
iptal önizlemesinin değişiklik yapmamasını, süreç ortamının korunmasını,
yanlış sohbet iptalini, SSE devam imlecini, arama kimliklerini ve silinmiş
hesap oturumlarını kapsıyor.

Tam test çalıştırmasında dört mevcut başarısızlık sürüyor: iki macOS sandbox
entegrasyonunda `sandbox_apply: Operation not permitted`, iki WhatsApp HTTP
entegrasyonunda `httpx.ConnectError`. Bunlar atlanarak başarı ilan edilmedi.
Docker bu ortamda bulunmuyor. Mobil/masaüstü tarayıcı uçtan uca testleri henüz
yapılmadı; derleme başarısı kullanıcı deneyimi doğrulaması sayılmaz.

## Açık işler

### İkinci uygulama turu

- Web yürütücüsüne 120.000 karakter eşiğinde deterministik bağlam daraltma
  eklendi. Eski mesajların kısa alıntıları, güvenilmeyen oturum özeti olarak
  işaretleniyor; asıl geçmiş korunuyor. Bu, plandaki modelle semantik
  özetlemenin yerine geçen tam bir uygulama değildir.
- Kullanıcıya özel, 1 MB sınırlı UTF-8 metin dosyası yükleme ve arayüzden
  ekleme uygulandı. Dosyalar enjeksiyon taramasından ve sır maskelemeden
  geçiyor; mesaj başına en fazla dört dosyadan sınırlı metin ekleniyor.
  Görsel/PDF işleme, anlamsal parça sıralaması ve saklama kotası açık.
- STARTTLS ile SMTP giriş bağlantısı gönderimi ve tarayıcıda bağlantı
  doğrulaması eklendi. Geliştirme token'ı varsayılan olarak kapalı.
  Üretim başlangıcı en az 32 karakterlik anahtar ve güvenli çerez istiyor.
  SMTP_HOST, SMTP_PORT, SMTP_FROM, SMTP_USER, SMTP_PASSWORD değişkenlerinin
  adları MILYONUS_ önekiyle; HTTPS adresi MILYONUS_WEB_PUBLIC_URL ile ayarlanır.
  Gerçek teslimat, SMTP hesabı yapılandırılmadığı için doğrulanmadı.
- Kalıcı giriş/yükleme/mesaj hız sınırları eklendi; SQLite yazma işlemleri
  süreç içi kilitle seri yürütülüyor. Aylık kullanım sıfırlama düzeltildi.
  Token rezervasyonu ve gerçek dolar tavanı hâlâ açık.
- 16 web/bağlam testi geçti; bunlara 16 iş parçacığından 200 hız sınırı
  isteği, dosya boyutu/tür kontrolü ve kullanıcılar arası dosya izolasyonu
  dahil. Bu küçük eşzamanlılık testi üretim yük kabulü yerine geçmez.
  TypeScript/Vite derlemesi geçti; 500 kB paket uyarısı sürüyor.

- W1–W5: üretim e-posta teslimi, tam olay sözleşmesi testleri, yeniden yüklemede
  çalışan göreve bağlanma, araç sonuçları, kullanıcıya hata bildirimi, eksik
  sohbet eylemleri ve mobil uçtan uca kabulü.
- W6: güven sınırlarını koruyan semantik çağırma, bağlam sıkıştırma, ek dosya
  yükleme ve proje talimatlarının uçtan uca uygulanması.
- W7: kullanıcı başına kota/rezervasyon ve maliyet tavanı, hız sınırı, CSP,
  yük testi ve güvenlik değerlendirmesi. Yerel regresyonlar tek başına bu
  aşamayı tamamlamaz.
- W8: dağıtım, izleme/alarmlar, onboarding ve 20 gerçek dış kullanıcıyla beta.
- 5X: temsili görev dağılımı, iki sürümde en az 250'şer gerçek koşu, gerçek
  maliyet/fatura doğrulaması, bağımsız model koltukları, güven aralıkları,
  performans eşikleri ve bağımsız denetim. Mevcut CLI oracle izolasyonu bu
  oturumdaki macOS sandbox kısıtı nedeniyle doğrulanamıyor.
- Ana plan: gerçek Docker entegrasyonu ve bağımsız güvenlik denetimi.

### Üçüncü uygulama turu

- Her model çağrısından önce SQLite ile atomik aylık token/maliyet rezervasyonu
  eklendi. Başarılı çağrıda kullanım farkı iade edilir; kesinti ve eksik kullanım
  bilgisinde rezervasyon korunur. Araç döngülerindeki çağrılar da kapsanır.
- Fiyatlar açık yapılandırma ister; maliyet tavanı etkinse eksik fiyatla çağrı
  yapılmaz. Dolar hesabı tahminidir, fatura tavanı garantisi değildir.
- 200 isteğin 16 iş parçacığı ve bağımsız bağlantılarla yarıştığı kota testi,
  maliyet sınırı, kullanıcı izolasyonu, hata rezervasyonu ve ay değişiminde
  yanlış iade kontrolü eklendi. Web testleri toplam 19 testle geçti.
- Kimliği doğrulanmış HTTP yük probu `scripts/web_load.py` eklendi; gerçek
  dağıtım adresi/oturumu olmadığından üretim sonucu üretilmedi. Kapsam ve
  yapılandırma `docs/web-quota-and-validation.md` belgesinde açıklanıyor.
- Yukarıdaki eski token rezervasyonu açık kaydı bu uygulamayla ilerletildi;
  üretim yük kabulü, dış beta, faturalı 5X deneyleri ve bağımsız denetim açık.

Kullanıcı izni bu teknik bağımlılıkların ve ölçüm kanıtlarının yerine geçmez.
5X kazanç, bağımsız denetim veya beta sonuçları yapılmadan yapılmış sayılmaz.

### Dördüncü uygulama turu — CLI kısıtı ve dosya bağlamı

- Kullanıcının model çalıştırma tercihi yalnız Antigravity veya ChatGPT/Codex
  CLI olarak sabitlendi. Bu turda sağlayıcı API'si veya ücretli model çağrısı
  yapılmadı. Kurulu `codex` komutu bulundu; Antigravity PATH üzerinde bulunmadı.
- macOS koruma ön kontrolü yeniden çalıştırıldı: `sandbox-exec` en basit
  `true` komutunda bile `sandbox_apply: Operation not permitted` döndürüyor.
  Gizli oracle koruması kaldırılmadı; gerçek 5X koşuları başlatılmadı.
- W6 dosya bağlamında sabit ilk 6000 karakter yerine, 2000 karakterlik ve
  400 karakter örtüşen parçalar soruyla kelime örtüşmesine göre sıralanıyor.
  Bu yöntem deterministik sözcüksel aramadır; anlamsal arama değildir.
- Eklerin tamamı kaynak kimliği ve metin ofsetiyle işaretleniyor; XML kaçışları
  ve etiketler dahil toplam 24.000 karakter sınırı uygulanıyor. Aynı ek kimliği
  mesajda bir kere işleniyor. Saklanan dosyalar değiştirilmedi.
- Üç yeni regresyon: dosya sonundaki ilgili parçayı bulma, tüm dosyalar ve
  kaçış karakterleri dahil ortak bütçe, kaynak/etiket kaçışı ve kararlı sıralama.
- Tam Python testi: **428 geçti, 4 başarısız, 1 atlandı**. Başarısızlar önceki
  iki macOS sandbox ve iki yerel WhatsApp HTTP entegrasyonu. Değişen Python
  dosyalarında Ruff başarılı. Gerçek dağıtım, dış beta ve P5 kabulü hâlâ açık.
