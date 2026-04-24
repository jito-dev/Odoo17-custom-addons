/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { knowledgeTopbar } from "@knowledge/components/topbar/topbar";

patch(knowledgeTopbar.component.prototype, {
    async exportToMarkdown() {
        const articleId = this.props.record.resId;
        if (!articleId) {
            return;
        }
        await this.props.record.model.root.isDirty();
        await this.env._saveIfDirty();
        window.location.href = `/knowledge/article/${articleId}/export_markdown`;
    },

    importFromMarkdown() {
        const articleId = this.props.record.resId;
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".md,.markdown,.mdown,.mkdn,text/markdown,text/plain";
        input.style.display = "none";
        input.addEventListener("change", async (ev) => {
            const file = ev.target.files && ev.target.files[0];
            input.remove();
            if (!file) {
                return;
            }
            let content;
            try {
                content = await file.text();
            } catch (err) {
                this.env.services.notification.add(
                    _t("Could not read the selected Markdown file."),
                    { type: "danger" },
                );
                return;
            }
            await this.props.record.model.root.isDirty();
            await this.env._saveIfDirty();
            try {
                const newId = await this.orm.call(
                    "knowledge.article",
                    "jito_import_markdown",
                    [],
                    {
                        filename: file.name,
                        content: content,
                        parent_id: articleId || false,
                    },
                );
                if (newId) {
                    this.env.services.notification.add(
                        _t('Imported "%s" from Markdown.', file.name),
                        { type: "success" },
                    );
                    await this.env.openArticle(newId);
                }
            } catch (err) {
                // Let Odoo's default error dialog surface the server message.
                throw err;
            }
        });
        document.body.appendChild(input);
        input.click();
    },
});
