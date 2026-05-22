# Data Safety & Migration Guarantees

Документ-гарантія для впровадження `hr_recruitment_job_stage_config` і
суміжних модулів (per-job email templates, hide stages, call stage,
test task descriptions). Описує **що відбувається з існуючими даними**
при встановленні модуля, які захисні механізми задіяні і як зробити
rollback, якщо щось пішло не так.

> **Головна гарантія:** міграція **additive only** — тільки додає рядки
> у нову таблицю `hr.job.stage.config`. Жодна існуюча стадія, вакансія
> чи кандидат не видаляється, не перейменовується, не змінює свій
> `stage_id` під час міграції.

---

## 1. Які об'єкти існують ДО встановлення модуля

| Модель | Що в ній | Чи міняємо |
|---|---|---|
| `hr.recruitment.stage` | Список стадій (Initial Qualification, Test Task, …). Поля: `name`, `sequence`, `job_ids` (M2M), `template_id`, `hired_stage`, `fold`, … | **Читаємо** для міграції. Додаємо нове поле `scope` (computed/stored, з дефолтом за станом `job_ids`). Існуючі рядки не видаляються. |
| `hr.job` | Вакансії. | Додаємо `One2many stage_config_ids`. Існуючі вакансії не чіпаємо. |
| `hr.applicant` | Кандидати з прив'язкою `stage_id` до конкретної стадії. | **Не чіпаємо взагалі.** `stage_id` не модифікується скриптом міграції. |
| `mail.template` | Email-шаблони, на які посилається `stage.template_id`. | Не чіпаємо. |

---

## 2. Що робить post-migrate скрипт (покроково)

Скрипт виконується **один-єдиний раз** при встановленні модуля
(`migrations/17.0.<version>/post-migrate.py`).

```python
def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Config = env['hr.job.stage.config']

    for stage in env['hr.recruitment.stage'].search([]):
        if stage.job_ids:
            # було specific у старій моделі → створюємо config-рядки
            for job in stage.job_ids:
                # idempotent: skip якщо рядок уже існує
                exists = Config.search_count([
                    ('job_id', '=', job.id),
                    ('stage_id', '=', stage.id),
                ])
                if not exists:
                    Config.create({
                        'job_id': job.id,
                        'stage_id': stage.id,
                        'visible': True,
                        'mail_template_id': stage.template_id.id or False,
                        'sequence': stage.sequence,
                    })
            stage.scope = 'specific'
        else:
            stage.scope = 'global'
        # stage.job_ids, stage.template_id, stage.sequence — НЕ ЧІПАЄМО
```

**Що гарантовано НЕ робиться:**

- ❌ `stage.unlink()` — жодна стадія не видаляється.
- ❌ `applicant.stage_id = …` — жоден кандидат не пересувається.
- ❌ `stage.job_ids = []` — M2M не очищається (лишається для backward
  compatibility з можливими сторонніми модулями).
- ❌ `stage.template_id = False` — глобальний fallback-шаблон зберігається.
- ❌ Перейменування або зміна `sequence` існуючих стадій.

**Idempotency:** скрипт можна запустити двічі (наприклад, при upgrade
модуля) — `search_count` гарантує відсутність дублікатів.

---

## 3. Що бачить рекрутер ВІДРАЗУ після встановлення

### Кейс A: вакансія з тільки глобальними стадіями

Це більшість поточних вакансій (всі, крім тих, де хтось вручну
заповнював `job_ids` або де `hr_recruitment_test_task` додавав себе).

**До оновлення** kanban показував N колонок (Initial Qualification,
Test Task, Interview, Offer, Hired).

**Після оновлення** kanban показує **тих самих N колонок у тому ж
порядку**. У формі вакансії з'являється нова вкладка **Stages** з
переліком цих стадій (всі `visible=True`, без overrides) — повна
поведінка ідентична до встановлення.

### Кейс B: вакансія, де `hr_recruitment_test_task` додав специфічні стадії

Зараз модуль `hr_recruitment_test_task` при `add_test_task=True`
шукає стадії "Test Task", "Test Task in progress", "Test Task Done"
і додає вакансію в їх `job_ids`. Також пише `stage.template_id =
mail_template_test_task_invite` (з коментарем `# CRITICAL FIX` — це
відомий source of bugs, бо template глобальний, а потрібен per-job).

**Після оновлення:**
- Міграція створить для кожної з цих 3 стадій рядок
  `hr.job.stage.config(job=цей_job, stage=стадія, visible=True,
  mail_template_id=mail_template_test_task_invite)`.
- Kanban виглядає ідентично.
- Тепер шаблон тест-таску **локальний для цієї вакансії** — якщо
  інший рекрутер захоче інший шаблон у своїй Test Task стадії, він
  не перетре цей.

### Кейс C: кандидат стоїть на стадії

Жоден кандидат не змінює `stage_id`. Він залишається там, де був.
Видимість в kanban не змінюється (бо за дефолтом для всіх існуючих
стадій `visible=True`).

---

## 4. Чотири рівні захисту від втрати даних

### Рівень 1 — БД (foreign keys)

`hr.applicant.stage_id` має `ondelete='restrict'` у стандартному
Odoo. Це **фізичний барєр БД**: PostgreSQL не дасть видалити
рядок з `hr.recruitment.stage`, на який посилається хоча б один
`hr.applicant`. Це поведінка з коробки і ми її **не змінюємо**.

### Рівень 2 — Скрипт міграції (additive only)

Post-migrate тільки **читає** з `hr.recruitment.stage` і **пише** в
нову таблицю `hr.job.stage.config`. Не виконує `unlink()` / `write()`
по існуючих полях (крім нового `scope`, яке є computed-default).

### Рівень 3 — UI guards для деструктивних дій

- **Спроба сховати стадію (`visible=False`), де є кандидати →** модальний wizard з трьома опціями (перенести / все одно сховати / скасувати). Опція «Все одно сховати» вимагає додаткового підтвердження.
- **Спроба видалити стадію через UI →** стандартний Odoo error «You cannot delete stages with applicants».
- **Спроба перевести стадію `global → specific` так, щоб втратити кандидатів →** wizard зі списком таких кандидатів і опцією додати вакансії в `job_ids` або перенести кандидатів.

### Рівень 4 — Rollback (деінсталяція модуля)

Якщо щось пішло не так після встановлення:

```bash
# через UI: Apps → hr_recruitment_job_stage_config → Uninstall
# або CLI:
odoo-bin -d <dbname> -u base --uninstall hr_recruitment_job_stage_config
```

При деінсталяції Odoo автоматично:
- Видаляє таблицю `hr_job_stage_config` (всі config-рядки зникають).
- Видаляє додані поля з `hr.recruitment.stage` (`scope`) і `hr.job`
  (`stage_config_ids` — це One2many, фізичного поля немає).
- НЕ чіпає `hr.recruitment.stage`, `hr.job`, `hr.applicant` рядки.

**Стан БД після rollback ідентичний стану до встановлення** (з
точністю до auto-incremented IDs у нових таблицях, які зникають).

---

## 5. Передпродакшн чеклист

Перед встановленням на прод:

- [ ] **Бекап БД** (`pg_dump`) — must-have перед будь-яким Odoo upgrade.
- [ ] **Встановити на staging-копії прода**, перевірити:
  - [ ] 5 ключових вакансій відкриваються, kanban виглядає ідентично.
  - [ ] Випадково обрані 10 кандидатів стоять на тих самих стадіях.
  - [ ] `hr_recruitment_test_task` стадії (Test Task / Test Task in
    progress / Test Task Done) працюють як раніше; email на зміну
    стадії розсилається з тим самим шаблоном.
  - [ ] Створення нового кандидата на вакансії проходить через
    `_compute_stage_id` і потрапляє на правильну дефолтну стадію.
- [ ] **Прогнати автотести** (див. §6).
- [ ] **Створити «канарку»**: одну тестову вакансію з 2 кандидатами
  на staging, провести через всі стадії, перевірити email.
- [ ] **Виконати rollback** на staging, переконатися що стан БД
  відновлюється до pre-install.

---

## 6. Автотести міграції

Файл: `hr_recruitment_job_stage_config/tests/test_migration.py`.

```python
class TestMigration(TransactionCase):
    def test_global_stage_stays_global(self):
        """Стадія без job_ids → scope='global', config-рядки не створені."""

    def test_specific_stage_creates_configs(self):
        """Стадія з job_ids=[A, B] → 2 config-рядки, visible=True,
           mail_template_id=stage.template_id, sequence=stage.sequence."""

    def test_applicants_keep_their_stage(self):
        """Снапшот applicant.stage_id ДО та ПІСЛЯ міграції — ідентичний."""

    def test_idempotent_rerun(self):
        """Повторний запуск post-migrate не створює дублікатів."""

    def test_kanban_visibility_unchanged(self):
        """_read_group_stage_ids повертає той самий набір стадій
           для кожної існуючої вакансії, що й до встановлення модуля."""

    def test_uninstall_clean(self):
        """Після uninstall — таблиця config зникає, applicants
           і stages цілі."""
```

Тести запускати на снапшоті продової структури (через
`odoo-bin shell` + `pg_dump --schema-only` на dev DB).

---

## 7. Що НЕ покрито гарантіями (відомі обмеження)

- **Сторонні модулі, які пишуть у `stage.template_id` глобально.**
  Якщо існує інший модуль (крім `hr_recruitment_test_task`, який ми
  рефакторимо в PR 2), що пише в `stage.template_id` напряму — він
  продовжить це робити. Це не зламає міграцію, але per-job overrides
  можуть несподівано перетиратися. Аудит сторонніх модулів — окрема
  передробота (`grep -r "template_id" jito_modules/`).
- **Кастомні звіти (BI / SQL), що джойнять `hr.recruitment.stage`
  через `job_ids`.** Лишаються робочими (поле `job_ids` ми не
  чіпаємо), але «правда» тепер у `hr.job.stage.config`. Звіти
  поступово переводимо на нову модель.
- **Експортовані CSV / API integrations (Genio ATS, etc.).** API
  endpoint `hr.applicant.stage_id` стабільний — не ламається. Але
  per-job метадані (template, hidden) недоступні через стандартний
  applicant API, потрібен окремий endpoint.

---

## 8. Інциденти / контактні точки

Якщо після міграції рекрутер каже «у мене зникла стадія» —
послідовність діагностики:

1. **Перевір `applicant.stage_id`** для конкретного кандидата:
   `SELECT id, name, stage_id FROM hr_applicant WHERE id=<X>` — якщо
   `stage_id` існує і ненульове, кандидат фізично на стадії,
   просто колонка прихована.
2. **Перевір config-рядок:**
   `SELECT * FROM hr_job_stage_config WHERE job_id=<J> AND stage_id=<S>`.
   Якщо `visible=False` — стадія прихована для цієї вакансії, фікс:
   відкрити форму вакансії → вкладка Stages → секція Hidden stages
   → toggle Visible.
3. **Перевір scope стадії:**
   `SELECT scope, job_ids FROM hr_recruitment_stage WHERE id=<S>`.
   Якщо `scope='specific'` і поточної вакансії немає в `job_ids` —
   стадія обмежена іншими вакансіями; фікс: додати цю вакансію в
   job_ids або перевести scope='global'.
4. **Лог міграції:** post-migrate пише лог у `ir.logging` з тегом
   `hr_recruitment_job_stage_config.migration` — там видно, скільки
   config-рядків створено, для яких пар (job, stage).

---

## 9. TL;DR (для команди)

- ✅ Міграція тільки додає — нічого не видаляє і не пересуває.
- ✅ Жоден кандидат не змінює `stage_id` під час встановлення.
- ✅ Жодна стадія не видаляється — навіть якщо стане «осиротілою».
- ✅ Rollback через uninstall повертає БД у pre-install стан.
- ✅ Чотири рівні захисту: PG foreign keys + additive migration + UI
  wizards + clean uninstall.
- ⚠️ Перед прод-встановленням: бекап + staging тест + автотести.
