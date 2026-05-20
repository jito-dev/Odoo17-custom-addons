# HR Recruitment — Stage default_get fix

## Що робить модуль

Виправляє єдину локальну проблему стокової Odoo 17:

- **До встановлення:** натискаєш «+ Stage» у kanban-board кандидатів
  конкретної вакансії → нова стадія створюється з порожнім `job_ids` →
  одразу стає **глобальною** і з'являється у kanban всіх інших вакансій.
- **Після встановлення:** натискаєш «+ Stage» у kanban-board кандидатів
  конкретної вакансії → нова стадія створюється з
  `job_ids = [поточна_вакансія]` → видима **тільки** у цій вакансії.

Створення стадії з **Configuration → Recruitment → Stages** і далі —
без змін: `job_ids=[]`, стадія глобальна (стокова поведінка).

## Чому ця проблема існує

У стоковому
`odoo17_enterprise/odoo/addons/hr_recruitment/models/hr_recruitment_stage.py`:

```python
@api.model
def default_get(self, fields):
    if self._context and self._context.get('default_job_id') and not self._context.get('hr_recruitment_stage_mono', False):
        context = dict(self._context)
        context.pop('default_job_id')        # ← викидає job_id з контексту
        self = self.with_context(context)
    return super(RecruitmentStage, self).default_get(fields)
```

Стокова логіка свідомо викидає `default_job_id` з контексту перед
super, щоб нова стадія була «глобальною за замовчуванням». Прапор
`hr_recruitment_stage_mono` — escape hatch, але стандартний UI його
нігде не виставляє. Тому **усі** стадії, створені з kanban, ставали
глобальними.

Детальний root-cause аналіз — у
[`jito_modules/docs/recruitment_vacancy_stages_flow.md`](../docs/recruitment_vacancy_stages_flow.md) §4.

## Як саме модуль виправляє

Один метод-override у `models/hr_recruitment_stage.py`:

```python
class RecruitmentStage(models.Model):
    _inherit = 'hr.recruitment.stage'

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        job_id = self._context.get('default_job_id')
        if (
            job_id
            and not self._context.get('hr_recruitment_stage_mono', False)
            and 'job_ids' in fields
            and not self._context.get('default_job_ids')
            and not res.get('job_ids')
        ):
            res['job_ids'] = [(6, 0, [job_id])]
        return res
```

Тобто стокова поведінка з `pop('default_job_id')` зберігається
повністю — ми просто **після** super() повертаємо `job_ids` назад у
defaults на основі контексту, який наш `self` зберіг до super.

## Безпечні гарантії

- ❌ **Жодна існуюча стадія не модифікується.** Override торкається
  лише виклика `default_get` — він не пише в БД.
- ❌ **Жодних нових моделей / полів / таблиць / FK.**
- ❌ **Жодної міграції** (нема `migrations/`).
- ❌ **Жодних view-змін** (нема `data` у manifest).
- ❌ **Жодних змін у `odoo17_enterprise/` / `odoo17_community/`.**

## Escape hatches (опційно для інтеграцій)

Якщо інший модуль свідомо хоче створити **глобальну** стадію з
контексту, де є `default_job_id`, є дві альтернативи:

1. `with_context(hr_recruitment_stage_mono=True)` — використовує
   документований стоковий escape hatch.
2. `with_context(default_job_ids=[(6, 0, [...])])` — явно задає
   власне значення для `job_ids`, наш override це поважає.

## Тести

`tests/test_default_get.py` — 7 кейсів:

1. `test_stage_from_kanban_is_job_specific` — +Stage з kanban
   проставляє `job_ids` поточної вакансії.
2. `test_stage_from_configuration_is_global` — без контексту job
   `job_ids` лишається порожнім.
3. `test_explicit_default_job_ids_respected` — явний
   `default_job_ids` від caller-а не перетирається.
4. `test_mono_flag_escape_hatch` — `hr_recruitment_stage_mono=True`
   повертає стокову поведінку.
5. `test_full_create_flow_with_kanban_context` — end-to-end через
   `create()` з kanban-контекстом.
6. `test_existing_global_stages_unchanged` — стара глобальна стадія
   після створення нової специфічної лишається глобальною.
7. `test_default_get_without_job_ids_in_fields` — якщо fields не
   запитує `job_ids`, override нічого не додає.

Запустити локально:

```bash
odoo-bin -c <conf> -i hr_recruitment_stage_default_fix \
    --test-enable --stop-after-init --log-level=test
```

## Rollback

```
Apps → HR Recruitment — Stage default_get fix → Uninstall
```

Стан БД після uninstall **ідентичний** стану до install — нічого не
писалось.

## Контекст у roadmap

Це **PR 1a** з [`recruitment_master_plan.md`](../docs/recruitment_master_plan.md) —
найшвидша й найбезпечніша частина master-plan. Закриває user-visible
баг, не блокуючи решту roadmap (per-job stage config, hide stages,
test task per job, call stage, form restructure — окремий PR 1b і далі).

Після PR 1b (повна foundation з `hr.job.stage.config` through-model)
цей модуль можна або:
- **Залишити** як standalone fix (depend-friendly);
- **Поглинути** у `hr_recruitment_job_stage_config` (depends → видалити).

Рішення про долю модуля — у момент мерджу PR 1b.

## Patterns / Constraints

- Один model-override, один файл (per CLAUDE.md «one model per file»).
- Без demo data (per CLAUDE.md).
- Версія `17.0.1.0.0` (нова мажорна, перша мінорна для модуля).
- LGPL-3, як решта jito_modules.
