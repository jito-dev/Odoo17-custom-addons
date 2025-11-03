# Odoo 17 AI Recruitment Addons

This repository contains custom **Odoo 17** modules designed to supercharge the HR Recruitment process by integrating Generative AI for automatic CV (Curriculum Vitae) data extraction.

These modules add a button to the Applicant form that scans the attached CV and uses an AI model to automatically fill in the applicant's details, such as name, email, phone number, LinkedIn profile, degree, and professional skills.

## Addons Included

1. **HR Recruitment OpenAI** (`hr_recruitment_openai`): Uses the OpenAI API to extract CV data.

2. **HR Recruitment Gemini** (`hr_recruitment_gemini`): Uses the Google Gemini API to extract CV data.

## Installation
These modules require external Python libraries to function. Before you can use an addon, you must install its dependencies.

1. Open the `requirements.txt` file in the root of this repository.

2. **Uncomment** the line for the addon(s) you plan to install. For example:

    - To use `hr_recruitment_openai`, uncomment `openai==2.6.1`.

    - To use `hr_recruitment_gemini`, uncomment `google-generativeai==0.8.5`.

3. Save the file.

4. Install the selected dependencies using pip:

       pip install -r requirements.txt

## 1. HR Recruitment OpenAI

This module integrates the OpenAI API to provide `"Extract with OpenAI"` functionality on Odoo Applicant records. It sends the applicant's CV file directly to the OpenAI API and parses the returned JSON to populate the form.

### Features

- **Smart Extraction**: Parses CVs (PDF, DOCX, images) for key applicant data.

- **Automatic Field Population**: Fills in _Name_, _Email_, _Phone_, _LinkedIn Profile_, and _Degree_.

- **Advanced Skill Matching**: Automatically finds or creates _Skill Types_, _Skills_, and _Skill Levels_ from the CV and links them to the applicant.

- **Background Processing**: All API calls run in a background thread to prevent UI lag.

- **Robust Error Handling**: Displays clear error or success messages to the user.

### Dependencies

- **Odoo Modules:**

  - `hr_recruitment`
  - `mail`
  - `hr_recruitment_skills` (Required for processing and saving skills)

- **Python Libraries:**

  - `openai` (See `requirements.txt` to install)


### Configuration

1. **Get your API Key**:

    - Go to the OpenAI Platform (https://platform.openai.com/) and sign up.

    - Navigate to the "API keys" section and create a new secret key.

2. **Configure in Odoo**:

    - In Odoo, go to `Settings > Human Resources`.

    - You will see a new section: **CV Data Extraction (OpenAI)**.

    - Set **CV Data Extraction (OpenAI)** to _"Extract on demand only"_.

    - Paste your secret key into the **OpenAI API Key** field.

    - The **OpenAI Model** defaults to `gpt-4o-mini`, which is recommended. You can change this to `gpt-4o` or another supported model if you wish.

### Usage

1. Navigate to the `Recruitment` application in Odoo.

2. Create a new applicant or open an existing one.

3. Ensure a CV file is attached as the main attachment.

4. Click the **"Extract with OpenAI"** button in the form header.

5. A status message will appear ("Pending", "Processing...").

6. Once complete (usually you need to reload the page), the form will refresh with the extracted data and skills populated. If an error occurs, a red status bar will show the error message.

## 2. HR Recruitment Gemini

This module integrates the Google Gemini API to provide "Extract with Gemini" functionality on Odoo Applicant records. It sends the applicant's CV file to the Gemini API and parses the returned JSON.

### Features

- **Smart Extraction**: Parses CVs for key applicant data using Google's Gemini models.

- **Automatic Field Population**: Fills in _Name_, _Email_, _Phone_, _LinkedIn Profile_, and _Degree_.

- **Advanced Skill Matching**: Automatically finds or creates _Skill Types_, _Skills_, and _Skill Levels_ from the CV.

- **Background Processing**: API calls run in a background thread to keep the UI responsive.

- **Robust Error Handling**: Clear status messages for users.

### Dependencies

- **Odoo Modules**:

  - `hr_recruitment`
  - `mail`
  - `hr_recruitment_skills` (Required for processing and saving skills)

- **Python Libraries**:

  - `google.generativeai` (See `requirements.txt` to install)

### Configuration

1. **Get your API Key**:

    - Go to Google AI Studio (https://aistudio.google.com/) (or Google Cloud Console).

    - Create a new project and generate an API key.

2. **Configure in Odoo**:

    - In Odoo, go to `Settings > Human Resources`.

    - You will see a new section: **CV Data Extraction (Gemini)**.

    - Set **CV Data Extraction (Gemini)** to _"Extract on demand only"_.

    - Paste your API key into the **Gemini API Key **field.

    - Set the **Gemini Model** (e.g., gemini-2.5-flash-lite).

### Usage

1. Navigate to the `Recruitment` application in Odoo.

2. Create or open an applicant record.

3. Attach a CV file.

4. Click the **"Extract with Gemini"** button.

5. The applicant's data will be extracted and populated in the form.
