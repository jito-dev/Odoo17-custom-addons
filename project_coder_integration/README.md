# Project Coder Integration

## Overview
Simple Odoo module that links project tasks to Coder.com workspaces with direct access links.

## Features
- Configure Coder.com API connection in Settings
- Link tasks to Coder workspaces
- Open workspaces directly from tasks
- Enable/disable integration per task

## Installation

### Prerequisites
- Odoo 17.0
- `project` module installed
- Python `requests` library
- Valid Coder.com account with API access

### Steps
1. Module location: `jito_modules/project_coder_integration/`
2. Restart Odoo server
3. **Settings → Apps → Update Apps List**
4. Search: **"Project Coder Integration"**
5. Click **Install**

## Configuration

### Initial Setup
1. Navigate to **Settings → General Settings**
2. Scroll to **Project** section → **Coder Integration**
3. Enable **Coder.com Integration**
4. Configure:
   - **Coder Base URL**: Your Coder URL (default: `https://coder.jito.dev`)
   - **API Token**: Generate from Coder → Settings → Tokens
5. Click **Test Connection** to validate
6. Click **Save**

## Usage

### Enable Integration on Task
1. Open any project task
2. Click **Enable Coder Integration** (header button)
3. **Coder Workspace** field appears in main form

### Link to Workspace
1. Select workspace from **Coder Workspace** dropdown
2. Click **Open** button to access workspace
3. Opens in new tab: `https://coder.jito.dev/@owner/workspace-name`

### Disable Integration
1. Click **Disable Coder Integration** button
2. Coder workspace field is hidden

## Architecture

### Models

**`res.company`** - Settings storage
- `coder_enabled`: Boolean
- `coder_api_token`: Char (secure)
- `coder_base_url`: Char

**`res.config.settings`** - Settings UI
- Related fields from `res.company`
- `action_test_coder_connection()`: Validates API

**`project.task`** - Task integration
- `coder_integration_enabled`: Boolean
- `coder_workspace_id`: Selection (dynamic)
- `action_enable_coder_integration()`
- `action_disable_coder_integration()`
- `action_open_coder_workspace()`

**`CoderAPI`** - API helper class
- `test_connection()`: Validates credentials
- `get_workspaces()`: Fetches user's workspaces

### API Endpoints Used
- `GET /api/v2/users/me` - Authentication validation
- `GET /api/v2/workspaces?q=owner:me` - List user workspaces

## File Structure
```
project_coder_integration/
├── __init__.py
├── __manifest__.py
├── README.md
├── models/
│   ├── __init__.py
│   ├── res_company.py
│   ├── res_config_settings.py
│   ├── project_task.py
│   └── coder_api.py
├── views/
│   ├── res_config_settings_views.xml
│   └── project_task_views.xml
└── security/
    └── ir.model.access.csv
```

## Security
- API tokens stored securely (no copy on duplicate)
- Settings restricted to administrators
- Task integration available to project users
- No credentials in logs

## Troubleshooting

### "Connection to Coder timed out"
- Check network connectivity
- Verify Coder deployment is accessible

### "Authentication failed"
- Verify API token is correct
- Check token hasn't expired
- Regenerate token if needed

### "No workspaces found"
- Ensure user owns workspaces in Coder
- Check API permissions

## Technical Details

### Workspace URL Format
```
{base_url}/@{owner_name}/{workspace_name}
```

Example:
```
https://coder.jito.dev/@zakhar-bozhok-jito/billing-module
```

### API Authentication
All requests use `Coder-Session-Token` header.

### Error Handling
- All API calls wrapped with comprehensive error handling
- User-friendly error messages
- Detailed logging for troubleshooting

## Version History

### 17.0.1.0.7
- Simplified to workspace selection and direct link
- Removed status tracking and controls
- Moved workspace field to main form
- Clean, minimal interface

## License
LGPL-3
