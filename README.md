# gravelscout

Мониторинг сербских досок объявлений в поисках конкретного гравийника.

## Что ищем

| Критерий | Значение |
|---|---|
| Тип | gravel / циклокросс (не шоссер, не туринг, не MTB) |
| Трансмиссия | Shimano GRX (любой), Tiagra 2x10, 105, Ultegra, SRAM Apex/Rival/Force, Campagnolo Ekar |
| Тормоза | только гидравлические дисковые |
| Руль | дропбар |
| Размер | 47–52 см, буквенные XXS/XS/S. 52 — потолок, 54 и 55 не рассматриваем |
| Ростовка | якорь — Liv Devote Advanced S (stack 558, reach 376), допуск ±28 мм по stack и ±18 мм по reach |
| Бренд | берём Rose, Giant, Liv, Specialized, Scott, Cannondale, Trek, Bianchi и равных им. Cube, Canyon, Axess, Focus, Ghost, Bergamont, KTM, Merida, Kross — нет |
| Рост райдера | если продавец сам пишет вилку («XS 150–165cm»), она решает: 167.5 вне неё — отказ |

Всё это лежит в `config.yaml` — правится без захода в код.

All-road — не gravel. Rose Blend, Bianchi Impulso, Specialized Roubaix, Trek
Domane и прочие эндуранс-рамы уезжают в `reject` по имени модели, даже если в
объявлении написано «gravel»: дорожные зазоры, дорожная геометрия, покрышка до
35 мм. Туда же фитнесы на прямом руле (Sirrus, Metrix) и гоночные шоссеры
(Plasma, SuperSix, TCR) — у них правильная навеска и совершенно не тот
велосипед, а дропбар скаут выводит из манеток и на них ошибался бы.

Бренд — жёсткий фильтр, но только в одну сторону. Имя из `brands.reject` рубит
объявление, даже если всё остальное идеально: рама из «не вау» сегмента не
становится лучше от навешенного на неё GRX. А вот незнакомое имя — не отказ:
оно уходит в `unknowns` с пометкой «посмотри, что это за марка», потому что на
сербской доске регулярно всплывает что-то, чего нет ни в одном списке.

Райдер: рост 167–168, инсим 80–82. Отсюда считается посадочная высота седла
706–724 мм от каретки и предельный standover 780 мм.

## Как это работает

```
источники → парсинг → фильтр → оценка посадки → состояние → отчёт/уведомление
```

Три вердикта:

* **reject** — в объявлении прямо написано что-то дисквалифицирующее (MTB, ободные
  тормоза, Sora, рама 58).
* **maybe** — ничего не дисквалифицирует, но продавец не написал что-то важное.
  Именно такие объявления стоит открыть и написать продавцу.
* **match** — все жёсткие требования подтверждены текстом объявления.

Отдельно от `unknowns` есть `todos` — это не недостаток объявления, а работа:
«определить модель и год по фото, проверить геометрию на сайте производителя».

## Источники

| Ключ | Сайт | Почему |
|---|---|---|
| `2bike` | [2bike.rs / Cikloberza](https://www.2bike.rs/cikloberza/mali-oglasi/bicikli-6/gravel-ciklokros-189) | Есть отдельная категория Gravel/Ciklokros, продавцы честно пишут навеску |
| `kupujemprodajem` | [KupujemProdajem](https://www.kupujemprodajem.com/bicikli/drumski-trkacki/grupa/912/919/1) | Самый большой объём, гравийники лежат в «Drumski, trkački» |
| `polovniautomobili` | [Polovni Automobili](https://www.polovniautomobili.com/bicikli) | Большой раздел велосипедов |
| `lalafo` | [Lalafo.rs](https://lalafo.rs/serbia/bicikli) | Описания скудные, но объём есть |
| `halooglasi` | [Halo oglasi](https://www.halooglasi.com/sport-i-rekreacija/drumski-bicikli) | Разделы «Друмски» и «Остали» |

Ни у одного из них нет API, и разметку они время от времени меняют. Поэтому
парсер пробует три стратегии и берёт ту, что нашла больше:

1. встроенный JSON (`__NEXT_DATA__`, JSON-острова, flight-данные Next.js);
2. JSON-LD;
3. эвристика по HTML: найти ссылки, похожие на ссылки объявлений, и подняться
   до ближайшего родителя, в котором есть цена.

Третья стратегия продолжает работать даже после редизайна — в этом весь смысл.

### Когда источник отвечает 403

`2bike.rs` и `polovniautomobili.com` стоят за Cloudflare и с серверных адресов
(облако, GitHub Actions, VPN) отдают JS-челлендж вместо страницы. Парсер тут ни
при чём — страницы просто не было. Скаут различает эти два случая: челлендж он
называет вслух (`HTTP 403, Cloudflare challenge`) и до конца прохода больше в
этот домен не стучится, вместо того чтобы полторы минуты перебирать страницы,
которые все ответят одинаково.

Это касается не только 2bike: из облака закрыты четыре источника из пяти —
`2bike`, `polovniautomobili`, `lalafo`, `halooglasi`. Открыт только
KupujemProdajem, он же самый крупный. То есть Actions видит примерно половину
рынка, и именно ту половину, где нет отдельной категории Gravel/Ciklokros.

С домашнего сербского провайдера все пятеро обычно открываются. Поэтому все
источники включены в конфиге: в облаке заблокированные просто честно скажут
`HTTP 403, Cloudflare challenge` и пропустятся, а локальный прогон соберёт всё.

### Локальный прогон

Один раз:

```bash
git clone -b claude/repository-context-ojbu7t https://github.com/Dealegate/Cycling.git
cd Cycling
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`-b` обязателен, пока эта ветка не влита: ветка по умолчанию — старая, в ней нет
ни фильтра по брендам, ни потолка 52, ни `requirements-minimal.txt`.

Дальше каждый раз:

```bash
git pull
python -m gravelscout probe          # проверить, что доски открываются
python -m gravelscout run --all      # полный проход, отчёт в out/shortlist.md
```

`probe` — первое, что стоит запустить: если напротив источника стоит число, он
живой; если `Cloudflare challenge` — закрыт и с этой машины.

Результат лежит в `out/shortlist.md` (всё) и `out/new.md` (появившееся с
прошлого раза). Чтобы «новое» считалось правильно, состояние надо вернуть в
репозиторий:

```bash
git add data/seen.json && git commit -m "scout: local run" && git push
```

### С телефона

Телефон в Сербии — такой же «домашний» адрес, как ноутбук, поэтому 2bike и
остальные четыре доски с него открываются. Компилятора на телефоне нет, поэтому
ставить надо `requirements-minimal.txt` — там только чистый Python. Без `lxml`
скаут берёт парсер из стандартной библиотеки; на фикстурах и на живой странице
KupujemProdajem в 769 КБ оба парсера дают одинаковый список объявлений, так что
теряется только скорость.

**Android — Termux** (ставить с [F-Droid](https://f-droid.org/packages/com.termux/),
версия из Play Store заброшена):

```bash
pkg install -y python git clang
git clone -b claude/repository-context-ojbu7t https://github.com/Dealegate/Cycling.git
cd Cycling
pip install -r requirements-minimal.txt
python -m gravelscout probe
python -m gravelscout run --all
```

`clang` в списке не для красоты: Termux — это Android, а не glibc-линукс, и
готовые колёса с PyPI ему не подходят. Проверено на живом телефоне: `requests` и
`beautifulsoup4` приезжают готовыми, а PyYAML собирается на месте
(`pyyaml-6.0.3-cp314-cp314-android_24_arm64_v8a.whl`) — без компилятора pip
встанет именно на нём.

Первый запуск Termux печатает две простыни, которые выглядят тревожно и таковыми
не являются: перебор зеркал (репозиторий пакетов ещё не выбран, `bad` напротив
части зеркал значит «недоступно отсюда») и генерацию SSH-ключей — это `openssh`,
он приезжает прицепом к `git`. И то, и другое разово.

Termux умеет и по расписанию — `pkg install termux-services`, дальше обычный
cron. С настроенным телеграм-ботом (см. ниже) телефон становится полноценным
скаутом по тем доскам, которые Actions не видит.

**iOS** — сложнее и не проверено отсюда. В
[a-Shell](https://holzschu.github.io/a-Shell_iOS/) есть python3 и pip, ставятся
чистопитоновские пакеты; альтернатива — iSH с `apk add python3 py3-yaml`.
Если pip на чём-то споткнётся, скажите на чём, подберу замену.

Читать результат с телефона удобнее не из `out/shortlist.md`, а через телеграм:
экспортируйте `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` перед `run`, и каждый
новый кандидат придёт сообщением.

## Запуск

```bash
pip install -r requirements.txt

python -m gravelscout probe          # проверить, что источники парсятся
python -m gravelscout run            # один проход
python -m gravelscout run --watch --interval 20
python -m gravelscout check "Gravel bicikl, GRX 600 2x11, hidraulicne disk, vel 52"
```

`probe` при неудаче складывает сырой HTML в `debug/` — оттуда чинятся ссылки.

### По расписанию

`.github/workflows/scout.yml` крутится каждые 30 минут на GitHub Actions:
прогоняет тесты, обходит источники, коммитит `data/seen.json` обратно в репозиторий
и заводит issue на каждого нового кандидата. Ничего разворачивать не нужно —
достаточно включить Actions в репозитории.

### Уведомления в телеграм

1. Написать [@BotFather](https://t.me/BotFather), команда `/newbot`, получить токен вида `123456:AA...`.
2. Написать своему новому боту любое сообщение — пока вы не написали первым, Telegram не отдаст боту ваш chat_id.
3. Узнать chat_id:

```bash
export TELEGRAM_BOT_TOKEN=123456:AA...
python -m gravelscout telegram      # покажет chat_id
export TELEGRAM_CHAT_ID=...
python -m gravelscout telegram      # пришлёт тестовое сообщение
```

4. Для запуска по расписанию положить оба значения в секреты репозитория:
   Settings → Secrets and variables → Actions → New repository secret,
   имена `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`. Воркфлоу их уже читает.

Issue на каждого кандидата заводятся параллельно, если есть `GITHUB_TOKEN` и
`GITHUB_REPOSITORY` — в Actions они подставляются сами. Без обоих каналов скаут
просто пишет `out/shortlist.md` и `out/new.md`.

## Геометрия

`data/geometry.yaml` — база ростовок. Пусто ≠ плохо: если модели там нет, скаут
честно пишет «посмотри геометрию руками», а не выдумывает числа.

```bash
# вбить цифры с сайта производителя
python scripts/fetch_geometry.py add --brand canyon --model grizl --years 2021 2022 \
  --source https://www.canyon.com/... \
  --size XS stack=542 reach=371 --size S stack=562 reach=376

# или попробовать снять таблицу со страницы
python scripts/fetch_geometry.py scrape --brand canyon --model grizl \
  --url https://geometrygeeks.bike/bike/canyon-grizl-al-2021/
```

У каждой строки есть `confidence`; `low` скаут отдельно проговаривает в отчёте.

## Состояние и повторные показы

`data/seen.json` помнит, что уже показывали. Объявление всплывает снова, если:

* цена упала минимум на `output.price_drop_alert_pct` процентов (по умолчанию 7);
* продавец дописал объявление, и оно из `reject` стало `match`/`maybe`.

## Тесты

```bash
python tests/test_scout.py
```

40 тестов, сеть не нужна. Фикстуры в `tests/fixtures/` синтетические —
они проверяют, что JSON-стратегия и HTML-стратегия работают каждая сама по себе.
Настоящие захваты страниц кладите туда же вместо них.
