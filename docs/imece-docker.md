# Yerel Docker doğrulaması

macOS için Docker CLI ve Colima Homebrew ile kuruldu. Test profili ayrı tutulur;
varsayılan Docker context değiştirilmez ve girişte otomatik servis kurulmaz.

```sh
colima start imece-tests --activate=false --cpu 2 --memory 2 --disk 10 --ssh-config=false
docker --context colima-imece-tests pull python:3.12-slim
mkdir -p "$HOME/.cache/imece-docker-tests"
TMPDIR="$HOME/.cache/imece-docker-tests" DOCKER_CONTEXT=colima-imece-tests \
  MILYONUS_TEST_DOCKER=1 uv run pytest -q
colima stop imece-tests
```

Colima'nın paylaştığı kullanıcı dizinindeki `TMPDIR`, sandbox bind mount'u
için gereklidir. Varsayılan macOS geçici dizini VM içinde bulunmayabilir.
Yürütücü Docker'ın tam yolunu çözer; yalnızca gerekli Docker istemci ayarlarını
alt sürece aktarır. Bu ayarlar konteynere ortam değişkeni olarak verilmez.
Konteyner ağı kapalı, dosya sistemi salt okunur, kullanıcı yetkisiz ve kaynak
sınırları etkindir. Gerçek izolasyon testi bunları davranış düzeyinde sınar.

Performans deneyi ayrıca sabit digest kullanmalıdır; bu belgedeki etiketle
yerel test geçirmek P5 imaj ve model kökeni kabulü yerine geçmez.
