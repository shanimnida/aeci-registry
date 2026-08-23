/**
 * Builds the AECI Member Profiling Form (online version, v3) in Google Forms.
 *
 * HOW TO RUN THIS — you do not need to know how to code.
 *   1. Sign in to the Google account the CHURCH controls (not a personal one).
 *   2. Go to https://script.google.com and click "New project".
 *   3. Delete whatever is in the editor and paste this whole file in.
 *   4. Click Save, then Run. Google will ask permission to create forms on
 *      your behalf the first time — approve it. It will warn that the script
 *      is "unverified"; that is because you wrote it yourself rather than
 *      publishing it to the add-on store, and is expected.
 *   5. The Execution log prints the edit link and the share link.
 *
 * WHY A SCRIPT rather than a list of questions to type in: there are 40-odd
 * questions and the consent wording is long. Typing it by hand invites a
 * dropped clause, and the consent text is the one part of this form that has
 * to be exactly right.
 *
 * BEFORE YOU SHARE THE FORM, do these three things by hand:
 *   - Fill in the church's registered address in the consent text (search for
 *     ADDRESS_PLACEHOLDER below, or edit it in the form afterwards).
 *   - Have the Board read the consent section. It is a data privacy notice
 *     under RA 10173, not marketing copy, and nobody in this project is a
 *     lawyer. See docs/ONLINE_FORM.md.
 *   - Responses > "Link to Sheets" to create the response spreadsheet.
 *
 * See docs/ONLINE_FORM.md for the printed standalone consent, what to do with
 * the response sheet, and what still has to change in AEGIS itself.
 *
 * A NOTE ON THE ORDER THINGS ARE BUILT IN, since it looks odd: every add*Item
 * call APPENDS to the end of the form, so the sections have to be built in the
 * order a member will read them. But a "go to section" choice needs the
 * section it points at to exist already. So the consent question is added
 * first with no choices, and its choices are attached at the very end, once
 * every page it can jump to has been created. Building all the page breaks up
 * front instead would put every question on the last page.
 */

var CHURCH = 'Avdei Elohim Church Inc.';
var ADDRESS_PLACEHOLDER = '[FILL IN: the church\'s registered address]';
var FORM_VERSION = 'v3 (August 2026)';

// The eleven committees a member may choose. Grievance and Reconciliation is
// the twelfth committee and is deliberately absent: it is appointed by the
// Board, never self-selected, so it must not appear as a tickable box.
var SELF_SELECTABLE_COMMITTEES = [
  'Sunshine',
  'General Services',
  'Property and Supplies',
  'Music and Arts',
  "Children's Ministry",
  'Youth',
  'Events',
  'Finance and Resource Accessing',
  'ICT',
  'Secretariat',
  'Food'
];


function createProfilingForm() {
  var form = FormApp.create('AECI Member Profiling Form');

  form.setDescription(
    CHURCH + ' — Member Profiling Form, ' + FORM_VERSION + '.\n\n' +
    'Please read the data privacy consent on the first page before you answer. ' +
    'Only your last name and first name are required. Leave anything else ' +
    'blank if you would rather not answer, or do not know it.'
  );
  form.setProgressBar(true);
  form.setCollectEmail(false);
  form.setAllowResponseEdits(false);
  form.setConfirmationMessage(
    'Thank you. Your details have gone to the Secretariat of ' + CHURCH + '. ' +
    'If you need to correct anything, please speak to the Secretariat.'
  );

  // --- Page 1: consent -------------------------------------------------
  form.addSectionHeaderItem()
    .setTitle('Data Privacy Consent')
    .setHelpText(consentText());

  // Choices are attached at the bottom of this function, once the sections
  // they jump to exist.
  var consentQuestion = form.addMultipleChoiceItem()
    .setTitle('Do you consent to ' + CHURCH + ' collecting and using your personal information as described above?')
    .setHelpText(
      'You must answer this before the rest of the form. If you list children ' +
      'further down, answering yes also gives your consent as their parent or ' +
      'guardian for their details.'
    )
    .setRequired(true);

  form.addSectionHeaderItem()
    .setTitle('Optional — greetings on the church Facebook page')
    .setHelpText(facebookConsentText());

  form.addMultipleChoiceItem()
    .setTitle('May we greet you by name on the ' + CHURCH + ' Facebook page for your birthday and wedding anniversary?')
    .setHelpText(
      'This is optional and separate. Saying no changes nothing else, and does ' +
      'not stop the church greeting you in person.'
    )
    .setRequired(true)
    .setChoiceValues([
      'Yes, you may post my name.',
      'No, please do not post my name.'
    ]);

  // --- Page 2: personal ------------------------------------------------
  var personalPage = form.addPageBreakItem().setTitle('1. Personal information');

  form.addTextItem().setTitle('Last Name').setRequired(true);
  form.addTextItem().setTitle('First Name').setRequired(true);
  form.addTextItem().setTitle('Middle Name');
  form.addTextItem()
    .setTitle('Suffix')
    .setHelpText('Jr., Sr., III, and so on. Leave blank if none.');
  form.addTextItem()
    .setTitle('Nickname')
    .setHelpText('The name you actually go by. This is the name used in greetings.');
  form.addDateItem().setTitle('Date of Birth').setIncludesYear(true);
  form.addTextItem().setTitle('Place of Birth');
  form.addMultipleChoiceItem()
    .setTitle('Sex')
    .setChoiceValues(['Male', 'Female']);
  form.addMultipleChoiceItem()
    .setTitle('Civil Status')
    .setChoiceValues(['Single', 'Married', 'Widowed', 'Separated', 'Annulled']);
  form.addTextItem()
    .setTitle('Nationality')
    .setHelpText('Leave blank if Filipino.');

  // --- Page 3: contact -------------------------------------------------
  form.addPageBreakItem().setTitle('2. Contact details');

  form.addParagraphTextItem()
    .setTitle('Home Address')
    .setHelpText('House or purok, barangay, municipality, province.');
  form.addTextItem()
    .setTitle('Mobile Number')
    .setHelpText('For example 0917 123 4567.');
  form.addTextItem().setTitle('Email');

  // --- Page 4: family --------------------------------------------------
  form.addPageBreakItem()
    .setTitle('3. Family')
    .setHelpText('Skip this section if it does not apply to you.');

  form.addTextItem()
    .setTitle('Spouse Name')
    .setHelpText('Full name. Leave blank if not married.');
  form.addDateItem().setTitle('Date of Marriage').setIncludesYear(true);

  // --- Page 5: children ------------------------------------------------
  // Five fixed slots, matching the printed form and the five pairs of columns
  // in docs/IMPORT_TEMPLATE.md. Google Forms has no repeating sections.
  form.addPageBreakItem()
    .setTitle('4. Children')
    .setHelpText(
      'One row per child, oldest first. Leave the rest blank. If you have more ' +
      'than five children, list the first five and tell the Secretariat about ' +
      'the others.'
    );

  for (var index = 1; index <= 5; index++) {
    form.addTextItem().setTitle('Child ' + index + ' Name');
    form.addDateItem().setTitle('Child ' + index + ' Date of Birth').setIncludesYear(true);
  }

  // --- Page 6: emergency contact ---------------------------------------
  form.addPageBreakItem()
    .setTitle('5. Emergency contact')
    .setHelpText('Someone the church should call if something happens to you at a church activity.');

  form.addTextItem().setTitle('Emergency Contact Name');
  form.addTextItem()
    .setTitle('Emergency Contact Relationship')
    .setHelpText('For example: spouse, parent, sibling, friend.');
  form.addTextItem().setTitle('Emergency Contact Number');

  // --- Page 7: committees and certification ----------------------------
  var committeePage = form.addPageBreakItem().setTitle('6. Committees');

  form.addCheckboxItem()
    .setTitle('Committees you wish to be part of')
    .setHelpText(
      'Please choose up to two. If you tick more, the church will still accept ' +
      'your form — the Secretariat will simply check with you.'
    )
    .setChoiceValues(SELF_SELECTABLE_COMMITTEES);

  form.addParagraphTextItem()
    .setTitle('Anything else the Secretariat should know')
    .setHelpText('Optional.');

  form.addSectionHeaderItem()
    .setTitle('Certification')
    .setHelpText(
      'By submitting this form you certify that the information you have given ' +
      'is true and correct to the best of your knowledge. The date and time of ' +
      'your submission is recorded automatically.'
    );

  // --- Page 8: the decline branch --------------------------------------
  var declinedPage = form.addPageBreakItem().setTitle('Your details will not be recorded');

  form.addSectionHeaderItem()
    .setTitle('That is completely fine.')
    .setHelpText(
      'It does not affect your membership or your welcome at ' + CHURCH + ' in ' +
      'any way.\n\n' +
      'Because the church cannot hold your personal information without your ' +
      'consent, the rest of this form has been skipped. Please press Submit ' +
      'below — nothing else is kept.\n\n' +
      'If you have questions about what the church does with members\' ' +
      'information, or if you change your mind later, please speak to the ' +
      'Secretariat.'
    );

  // --- Navigation, now that every target page exists --------------------
  consentQuestion.setChoices([
    consentQuestion.createChoice('Yes, I consent.', personalPage),
    consentQuestion.createChoice('No, I do not consent.', declinedPage)
  ]);

  // Section 6 is the end of the form for anyone who consented; without this
  // they would fall through into the decline page.
  committeePage.setGoToPage(FormApp.PageNavigationType.SUBMIT);

  Logger.log('Edit the form here:  %s', form.getEditUrl());
  Logger.log('Share this link:     %s', form.getPublishedUrl());
  Logger.log('Now: fill in the church address, and have the Board read the consent.');
}


/**
 * The RA 10173 notice. Kept in one place so the online form and the printed
 * standalone consent in docs/ONLINE_FORM.md say the same thing — a register
 * that records "consented to v3" is worthless if the church cannot produce
 * the v3 wording.
 */
function consentText() {
  return [
    'Please read this before answering.',
    '',
    'WHO IS ASKING. ' + CHURCH + ' (AECI), a registered non-stock, non-profit ' +
      'religious corporation, with address at ' + ADDRESS_PLACEHOLDER + ', ' +
      'La Trinidad, Benguet.',
    '',
    'WHAT WE COLLECT. Your name and nickname, date and place of birth, sex, ' +
      'civil status, nationality, home address, mobile number, email address, ' +
      'the name of your spouse and your date of marriage, the names and birth ' +
      'dates of your children, your emergency contact, and the committees you ' +
      'wish to serve in.',
    '',
    'WHY WE COLLECT IT. To keep the church\'s official register of members; to ' +
      'reach you about services, activities and pastoral care; to organise the ' +
      'committees; to greet members on birthdays and wedding anniversaries; ' +
      'and to contact the person you name if there is an emergency at a church ' +
      'activity.',
    '',
    'SOME OF THIS IS SENSITIVE. Under the Data Privacy Act of 2012 (RA 10173), ' +
      'your civil status, your age and your religious affiliation are sensitive ' +
      'personal information, and your children\'s details are a minor\'s ' +
      'personal data. That is why we ask for your consent in writing instead of ' +
      'assuming it.',
    '',
    'WHO CAN SEE IT. Only the Secretariat, the ICT Committee and the Board of ' +
      'Directors can see a complete record. A committee chairperson sees only ' +
      'the name, mobile number and email address of the members of their own ' +
      'committee — not your address, birth date, civil status or family. We do ' +
      'not sell, rent or trade your information, and we do not give it to ' +
      'anyone outside the church except where the law requires it.',
    '',
    'HOW LONG WE KEEP IT. Your name, membership dates and status are part of ' +
      'the church register and are kept permanently, the way a church has ' +
      'always kept its roll. Your contact details — mobile number, email, home ' +
      'address and emergency contact — are erased two years after your record ' +
      'is marked transferred or deceased.',
    '',
    'YOUR RIGHTS. You may ask to see your record, have it corrected, object to ' +
      'how it is used, or ask that it be erased. You may withdraw this consent ' +
      'at any time; withdrawing it does not undo what was already done lawfully ' +
      'before you withdrew. To do any of these, speak to the Secretariat. You ' +
      'may also complain to the National Privacy Commission (privacy.gov.ph).'
  ].join('\n');
}


function facebookConsentText() {
  return [
    'This is a separate question, and your answer to it changes nothing else.',
    '',
    'The church Facebook page is PUBLIC. Anyone on the internet can see it, ' +
      'including people with no connection to the congregation.',
    '',
    'If you say yes, we would post only your name and the occasion — never your ' +
      'birth year, your age, your address, your phone number, your member ' +
      'number, or anything else about you.',
    '',
    'If you say no, the church will still greet you; it just will not do so on ' +
      'the public page. You may change your mind at any time by telling the ' +
      'Secretariat.'
  ].join('\n');
}
