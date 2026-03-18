# Jito Icons

Overrides root menu icons for Account, Settings, and Project apps with custom icons.

## Applying icon changes

Icons are updated when the module is **installed or upgraded** (via `post_init_hook`). To see changes:

### 1. Upgrade the module (required)

1. Enable Developer Mode: **Settings → Activate Developer Mode**
2. **Apps** → search "Jito Icons" → **Upgrade**
3. This runs `post_init_hook` and updates `web_icon` on the menus

### 2. Restart Odoo (required – clears server cache)

Menu data is cached with `@tools.ormcache_context`. Restart clears it:

```bash
# Stop Odoo (Ctrl+C if running in terminal)
./bin/odoo.sh start
```

### 3. Clear browser cache (required – clears client cache)

After restart, do a **hard refresh**:

- **Chrome/Edge**: Ctrl+Shift+R (Windows/Linux) or Cmd+Shift+R (Mac)
- **Firefox**: Ctrl+F5 (Windows/Linux) or Cmd+Shift+R (Mac)

Or clear site data for your Odoo URL in browser settings.

### 4. Service worker (if still cached)

Odoo may use a service worker. Clear it:

1. Open DevTools (F12)
2. **Application** tab → **Service Workers**
3. Click **Unregister** for your Odoo URL

## Quick checklist

- [ ] Upgrade `jito_icons` module
- [ ] Restart Odoo (`./bin/odoo.sh start`)
- [ ] Hard refresh browser (Ctrl+Shift+R)
- [ ] If needed: unregister service worker
