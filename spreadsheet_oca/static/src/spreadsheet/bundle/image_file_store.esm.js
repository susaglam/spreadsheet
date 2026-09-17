import {_t} from "@web/core/l10n/translation";
import {browser} from "@web/core/browser/browser";

/**
 * Returns the attachment id of a path built by ImageFileStore.upload().
 *
 * @param {String} path e.g. "/web/image/42?access_token=abc"
 * @returns {Number}
 */
function getAttachmentId(path) {
    const match = /\/web\/image\/(\d+)/.exec(path || "");
    if (!match) {
        throw new Error("Invalid path: " + path);
    }
    return parseInt(match[1], 10);
}

export class ImageFileStore {
    constructor(resModel, resId, http, orm) {
        this.resModel = resModel;
        this.resId = resId;
        this.http = http;
        this.orm = orm;
    }

    async upload(file) {
        const route = "/web/binary/upload_attachment";
        const params = {
            ufile: [file],
            csrf_token: odoo.csrf_token,
            model: this.resModel,
            id: this.resId,
        };
        const fileData = JSON.parse(await this.http.post(route, params, "text"))[0];
        const [accessToken] = await this.orm.call(
            "ir.attachment",
            "generate_access_token",
            [fileData.id]
        );
        return `/web/image/${fileData.id}?access_token=${accessToken}`;
    }

    async delete(path) {
        // The last path segment is "<id>?access_token=<token>": parse the id
        // explicitly instead of trusting Number.isNaN() on a string (never true).
        await this.orm.unlink("ir.attachment", [getAttachmentId(path)]);
    }

    /**
     * Used by o-spreadsheet (saas-19.4) to copy an image to the OS clipboard.
     *
     * @param {String} path
     * @returns {Promise<File>}
     */
    async getFile(path) {
        const response = await browser.fetch(path);
        if (!response.ok) {
            throw new Error(
                _t(
                    "The image could not be loaded (HTTP %(status)s), so it was not copied. Reload the spreadsheet and try again; if the image was deleted, insert it again.",
                    {status: response.status}
                )
            );
        }
        const blob = await response.blob();
        const name = path.split("?")[0].split("/").pop() || "image";
        return new File([blob], name, {type: blob.type});
    }
}
