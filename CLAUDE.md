# CLAUDE.md

You are an AI assistant working on this repository.  
Follow all instructions below strictly.

## Project Overview

This is an Odoo-based ERP platform with custom modules extending Odoo functionality.

## Architecture

- **Core Architecture**: Odoo Utilizes MVC.
- **Core Framework**: Odoo Enterprise (located in `odoo17_enterprise/odoo/`)
- **Custom Modules**: `jito_modules/` - Main development focus, do all the coding only here

## Important Development Guidelines

**CRITICAL**: When you are creating new addons, models, views, Owl components, CSS, JavaScript, and any other Odoo code, always reference Odoo source code from `odoo17_enterprise/odoo/addons/` rather than relying on your general Odoo knowledge. Your internal Odoo 17 knowledge is limited and may be outdated, so always consult the actual source.
When you're updateing Plugins/Addons increment module version.

**Primary Development Target**: Focus exclusively on `jito_modules/` – this is the only active folder for custom addons that we develop.

**View Conventions**:
- Always use `"tree"` view instead of `"list"` view in XML view definitions.
- We use Odoo 17, not earlier versions; you have limited knowledge of it, so you must consult the Odoo 17 source code for patterns and examples.

**Changes**:
- Never change files inside `odoo17_community/` folder.
- Never change files inside `odoo17_enterprise/` folder.


## Module Development Patterns
- Always use only Odoo 17 version APIs and patterns.
- Inherit from base Odoo models (e.g. hr.applicant, hr.job, etc.).
- Use proper field types (Binary for files, Char for filenames, etc.).
- Use separate files for each odoo.models.Model.
- Keep code files small; split into several files/modules if needed.
- Follow Odoo security model with proper access rights / access control lists.
- Do not create demo data; we do not need it.
- For every module that you develop or improve, create a small guidance file inside the module, describing:
- What the module does.
- Main models, views, and business logic.
- Any important patterns or constraints.
- Always ultrathink: carefully read existing code, compare with Odoo 17 source, plan changes before implementing, and keep behaviour safe and consistent.


## VERY IMPORTANT! -> SOFTWARE DEVELOPMENT LIFECYCLE <-
**VERY CRITIAL** 
You have to follow this workflow when building the software
### Planning & Feature Design
#### 1. Implementation Planning
- Plan & Design your solution first.
- DON'T go coding immediately.
- Propose several options for implementation & evaluate which will you choose. 
- When designing the solution take into consideration the: Quality of solution, User Experience, Supportability
- If you need ask more questions to plan your solution 
- As result create short document outlining this step results
#### 2. Implementation 
- Implement accoring to you plan from implementation planning
- Always ultrathink: carefully read existing code, compare with Odoo 17 source, plan changes before implementing, and keep behaviour safe and consistent.
#### 3. Hand-in results
- Provide concise summary on what have you done, locations of your testing results such as screenshots and recorded video or testing.

