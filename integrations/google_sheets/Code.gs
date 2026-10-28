/**
 * BotArba -> Google Таблицы.
 *
 * Принимает снимок базы от бота и перезаписывает два листа: «Сводка по дням»
 * и «Операции». Перезапись, а не добавление строк: расход могут отменить,
 * возврат уменьшает поступление, продажа с кассы Kaspi приходит задним числом
 * и встаёт в середину уже выгруженного дня. При перезаписи таблица всегда
 * в точности равна базе бота.
 *
 * Установка — см. README.md рядом с этим файлом.
 */

// ⚠️ ЗАМЕНИТЕ на свой пароль и впишите тот же самый в переменную
// SHEETS_TOKEN у бота. Любая длинная случайная строка.
const TOKEN = 'ЗАМЕНИТЕ_НА_СВОЙ_ПАРОЛЬ';

const OPERATIONS_SHEET = 'Операции';
const DAILY_SHEET = 'Сводка по дням';
const APP_STATS_SHEET = 'Статистика ArbaFood';

/**
 * Палитра. Чернила нейтральные, цвет несёт ровно один смысл — знак суммы.
 * Тип операции, статья и комментарий намеренно остаются серыми: если
 * раскрасить и их, цвет перестанет что-либо значить.
 */
const INK = '#0b0b0b';          // основной текст
const INK_SOFT = '#52514e';     // подписи, вторичные колонки
const INK_MUTED = '#898781';    // отменённое, служебное
const HEADER_BG = '#1a1a19';    // шапка таблицы
const HEADER_INK = '#f0efec';
const SURFACE = '#ffffff';
const BAND = '#f9f9f7';         // чередование строк, едва заметное
const RULE = '#e1e0d9';         // линейки
const POSITIVE = '#006300';     // приход
const NEGATIVE = '#d03b3b';     // расход

const FONT = 'Roboto';
const MONEY_FORMAT = '#,##0.##" ₸"';
const COUNT_FORMAT = '#,##0';
const PERCENT_FORMAT = '0.0%';

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return reply({ error: 'пустой запрос' });
    }

    const payload = JSON.parse(e.postData.contents);

    if (payload.token !== TOKEN) {
      // Не уточняем, что именно не так: адрес веб-приложения может утечь,
      // и подсказывать проверяющему нечего.
      return reply({ error: 'доступ запрещён' });
    }

    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    renderDaily(spreadsheet, payload);
    renderOperations(spreadsheet, payload.operations);
    // Блока может не быть, если бот старее скрипта — тогда лист не трогаем.
    if (payload.app_stats) {
      renderAppStats(spreadsheet, payload.app_stats);
    }
    orderSheets(spreadsheet);

    return reply({
      ok: true,
      operations: (payload.operations.rows || []).length,
      daily: (payload.daily.rows || []).length,
    });
  } catch (error) {
    return reply({ error: String(error) });
  }
}

function doGet() {
  // Открытие адреса в браузере не должно выглядеть как поломка.
  return reply({ ok: true, hint: 'Это приёмник данных BotArba. Нужен POST.' });
}

function reply(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Сводка — первым листом: её открывают чаще, чем журнал операций. */
function orderSheets(spreadsheet) {
  const daily = spreadsheet.getSheetByName(DAILY_SHEET);
  if (daily) {
    spreadsheet.setActiveSheet(daily);
    spreadsheet.moveActiveSheet(1);
  }
}

/** Лист под запись: создать, очистить, снять оформление прошлой выгрузки. */
function prepareSheet(spreadsheet, name, tabColor) {
  let sheet = spreadsheet.getSheetByName(name);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(name);
  }

  // Полосы и правила живут отдельно от содержимого: если их не снять,
  // с каждой выгрузкой они будут накапливаться поверх друг друга.
  sheet.getBandings().forEach(function (banding) { banding.remove(); });
  sheet.setConditionalFormatRules([]);
  const filter = sheet.getFilter();
  if (filter) {
    filter.remove();
  }

  sheet.clear();
  // clear() не разъединяет ячейки: объединения из шапки прошлой выгрузки
  // пережили бы очистку и сломали бы раскладку следующей.
  sheet.getRange(1, 1, sheet.getMaxRows(), sheet.getMaxColumns()).breakApart();
  sheet.setHiddenGridlines(true);
  sheet.setTabColor(tabColor);
  return sheet;
}

/**
 * Нарисовать шапку таблицы и тело, вернуть номер первой строки данных.
 * Общая часть обоих листов: шапка, чередование строк, выравнивание.
 */
function drawTable(sheet, header, rows, startRow, options) {
  const width = header.length;

  sheet.getRange(startRow, 1, 1, width)
    .setValues([header])
    .setBackground(HEADER_BG)
    .setFontColor(HEADER_INK)
    .setFontFamily(FONT)
    .setFontSize(10)
    .setFontWeight('bold')
    .setVerticalAlignment('middle')
    .setHorizontalAlignment('left');
  sheet.setRowHeight(startRow, 32);

  if (rows.length === 0) {
    sheet.getRange(startRow + 1, 1)
      .setValue('Пока нет данных')
      .setFontColor(INK_MUTED)
      .setFontFamily(FONT)
      .setFontStyle('italic');
    return startRow + 1;
  }

  // Строки могут быть разной длины, если бот обновится раньше скрипта —
  // добиваем до ширины заголовка, иначе setValues падает.
  const normalized = rows.map(function (row) {
    const copy = row.slice(0, width);
    while (copy.length < width) {
      copy.push('');
    }
    return copy;
  });

  const body = sheet.getRange(startRow + 1, 1, normalized.length, width);
  body.setValues(normalized)
    .setFontFamily(FONT)
    .setFontSize(10)
    .setFontColor(INK_SOFT)
    .setVerticalAlignment('middle');

  // Чередование строк вместо линеек: глаз ведёт по строке сам,
  // а сетка не спорит с цифрами.
  const banding = body.applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, false, false);
  banding.setHeaderRowColor(null)
    .setFirstRowColor(SURFACE)
    .setSecondRowColor(BAND);

  (options.moneyColumns || []).forEach(function (column) {
    sheet.getRange(startRow + 1, column, normalized.length, 1)
      .setNumberFormat(MONEY_FORMAT)
      .setHorizontalAlignment('right');
  });

  (options.percentColumns || []).forEach(function (column) {
    sheet.getRange(startRow + 1, column, normalized.length, 1)
      .setNumberFormat(PERCENT_FORMAT)
      .setHorizontalAlignment('right');
  });

  (options.countColumns || []).forEach(function (column) {
    sheet.getRange(startRow + 1, column, normalized.length, 1)
      .setNumberFormat(COUNT_FORMAT)
      .setHorizontalAlignment('right');
  });

  // Строки повыше: цифры не должны лепиться друг к другу.
  for (let row = startRow + 1; row <= startRow + normalized.length; row++) {
    sheet.setRowHeight(row, 26);
  }

  sheet.setFrozenRows(startRow);
  return startRow + normalized.length;
}

/**
 * Разлиновать таблицу.
 *
 * Скрытая сетка Sheets оставляет таблицу «висеть» в пустоте, особенно пока
 * строк мало. Явные границы дают ей края и ведут глаз по строке.
 */
function drawBorders(sheet, headerRow, lastRow, width) {
  const table = sheet.getRange(headerRow, 1, lastRow - headerRow + 1, width);
  table.setBorder(true, true, true, true, true, true, RULE,
                  SpreadsheetApp.BorderStyle.SOLID);

  // Под шапкой — линия потолще: она отделяет заголовки от данных.
  sheet.getRange(headerRow, 1, 1, width)
    .setBorder(null, null, true, null, null, null, HEADER_BG,
               SpreadsheetApp.BorderStyle.SOLID_MEDIUM);

  // Внешний контур тоже плотнее, иначе таблица расплывается по листу.
  table.setBorder(true, true, true, true, null, null, '#c3c2b7',
                  SpreadsheetApp.BorderStyle.SOLID);
}

/** Покрасить суммы по знаку: приход зелёным, расход красным. */
function moneySignRules(sheet, column, firstDataRow, lastRow) {
  if (lastRow < firstDataRow) {
    return [];
  }
  const range = sheet.getRange(firstDataRow, column, lastRow - firstDataRow + 1, 1);
  return [
    SpreadsheetApp.newConditionalFormatRule()
      .whenNumberGreaterThan(0).setFontColor(POSITIVE).setRanges([range]).build(),
    SpreadsheetApp.newConditionalFormatRule()
      .whenNumberLessThan(0).setFontColor(NEGATIVE).setRanges([range]).build(),
  ];
}

const OPERATIONS_WIDTHS = [56, 92, 64, 128, 116, 128, 260, 132, 150, 92];

function renderOperations(spreadsheet, block) {
  if (!block || !block.header) {
    return;
  }

  const sheet = prepareSheet(spreadsheet, OPERATIONS_SHEET, INK_SOFT);
  const rows = block.rows || [];
  const lastRow = drawTable(sheet, block.header, rows, 1, { moneyColumns: [5] });

  OPERATIONS_WIDTHS.forEach(function (width, index) {
    if (index < block.header.length) {
      sheet.setColumnWidth(index + 1, width);
    }
  });

  if (rows.length === 0) {
    return;
  }

  const width = block.header.length;
  const rules = [];

  // Отменённую операцию не прячем — её важно видеть, — но гасим целиком,
  // чтобы она не читалась как действующая. Правило идёт первым: при
  // совпадении нескольких правил выигрывает верхнее.
  rules.push(
    SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied('=$J2="да"')
      .setFontColor(INK_MUTED)
      .setStrikethrough(true)
      .setRanges([sheet.getRange(2, 1, lastRow - 1, width)])
      .build()
  );

  moneySignRules(sheet, 5, 2, lastRow).forEach(function (rule) {
    rules.push(rule);
  });

  sheet.setConditionalFormatRules(rules);

  // Дата и время — узкие служебные колонки, им приглушённый тон;
  // статья и комментарий несут смысл, их оставляем контрастнее.
  sheet.getRange(2, 1, lastRow - 1, 3).setFontColor(INK_MUTED);
  sheet.getRange(2, 6, lastRow - 1, 1).setFontColor(INK);
  sheet.getRange(2, 8, lastRow - 1, 3).setFontColor(INK_MUTED).setFontSize(9);

  drawBorders(sheet, 1, lastRow, width);
  sheet.getRange(1, 1, lastRow, width).createFilter();
}

const DAILY_WIDTHS = [110, 136, 136, 150, 136, 176, 90];

/**
 * Четыре показателя над таблицей: то, ради чего таблицу открывают.
 *
 * Каждая плитка занимает ДВЕ колонки: в одну подпись вида
 * «ПОСТУПЛЕНИЯ СЕГОДНЯ» не влезает и обрезается многоточием.
 */
function drawHeadline(sheet, summary, generatedAt, width) {
  const tiles = [
    { column: 1, label: 'БАЛАНС СЕЙЧАС', value: summary.balance, money: true, hero: true },
    { column: 3, label: 'ПОСТУПЛЕНИЯ СЕГОДНЯ', value: summary.today_income, money: true },
    { column: 5, label: 'РАСХОДЫ СЕГОДНЯ', value: summary.today_expense, money: true },
    { column: 7, label: 'ОПЛАТ', value: summary.today_payments, money: false },
  ];

  // Плитки — карточка на сером фоне: так блок читается как шапка,
  // а не как ещё одна строка данных.
  sheet.getRange(1, 1, 2, width)
    .setBackground(BAND)
    .setBorder(true, true, true, true, null, null, '#c3c2b7',
               SpreadsheetApp.BorderStyle.SOLID);

  tiles.forEach(function (tile) {
    const span = Math.min(2, width - tile.column + 1);
    const label = sheet.getRange(1, tile.column, 1, span);
    const value = sheet.getRange(2, tile.column, 1, span);
    if (span > 1) {
      label.merge();
      value.merge();
    }

    label.setValue(tile.label)
      .setFontFamily(FONT).setFontSize(9).setFontColor(INK_MUTED)
      .setHorizontalAlignment('left').setVerticalAlignment('middle');

    value.setValue(tile.value)
      .setFontFamily(FONT)
      .setFontSize(tile.hero ? 20 : 14)
      .setFontWeight('bold')
      .setFontColor(tile.value < 0 ? NEGATIVE : INK)
      .setHorizontalAlignment('left').setVerticalAlignment('middle');

    if (tile.money) {
      value.setNumberFormat(MONEY_FORMAT);
    }

    // Тонкая вертикаль между плитками вместо рамки вокруг каждой.
    if (tile.column > 1) {
      sheet.getRange(1, tile.column, 2, 1)
        .setBorder(null, true, null, null, null, null, RULE,
                   SpreadsheetApp.BorderStyle.SOLID);
    }
  });

  // Поступления всегда зелёные, даже когда их ноль: это постоянный смысл
  // колонки, а не свойство конкретного числа.
  sheet.getRange(2, 3).setFontColor(summary.today_income > 0 ? POSITIVE : INK_MUTED);

  // Отметка времени — отдельной строкой под карточкой. В узкой колонке
  // справа она обрезалась до «0.10.2026 в 09:55».
  sheet.getRange(3, 1, 1, Math.min(3, width)).merge()
    .setValue('Обновлено ' + (generatedAt || ''))
    .setFontFamily(FONT).setFontSize(9).setFontColor(INK_MUTED)
    .setHorizontalAlignment('left').setVerticalAlignment('middle');

  sheet.setRowHeight(1, 24);
  sheet.setRowHeight(2, 42);
  sheet.setRowHeight(3, 26);
}

function renderDaily(spreadsheet, payload) {
  const block = payload.daily;
  if (!block || !block.header) {
    return;
  }

  const sheet = prepareSheet(spreadsheet, DAILY_SHEET, INK);
  const rows = block.rows || [];

  if (payload.summary) {
    drawHeadline(sheet, payload.summary, payload.generated_at, block.header.length);
  }

  const headerRow = payload.summary ? 4 : 1;
  const lastRow = drawTable(sheet, block.header, rows, headerRow, {
    moneyColumns: [2, 3, 4, 5, 6],
    countColumns: [7],
  });

  DAILY_WIDTHS.forEach(function (width, index) {
    if (index < block.header.length) {
      sheet.setColumnWidth(index + 1, width);
    }
  });

  if (rows.length === 0) {
    return;
  }

  const firstDataRow = headerRow + 1;
  const rules = [];
  [2, 3, 4, 5].forEach(function (column) {
    moneySignRules(sheet, column, firstDataRow, lastRow).forEach(function (rule) {
      rules.push(rule);
    });
  });
  sheet.setConditionalFormatRules(rules);

  // Баланс на конец дня — итоговая колонка, её выделяем насыщенностью,
  // а не цветом: цвет уже занят знаком суммы.
  sheet.getRange(firstDataRow, 6, lastRow - headerRow, 1)
    .setFontColor(INK).setFontWeight('bold');
  sheet.getRange(firstDataRow, 1, lastRow - headerRow, 1).setFontColor(INK);
  sheet.getRange(firstDataRow, 7, lastRow - headerRow, 1).setFontColor(INK_MUTED);

  drawBorders(sheet, headerRow, lastRow, block.header.length);

  // Сегодняшний день — последняя строка: выделяем фоном, чтобы взгляд
  // падал на неё сразу при открытии.
  sheet.getRange(lastRow, 1, 1, block.header.length).setBackground('#f1f3f4');
}


const APP_STATS_WIDTHS = [100, 120, 160, 90, 130, 100, 110, 100, 100];

/**
 * Лист статистики приложения: строка на день.
 *
 * Заголовки, ширины колонок и подсказки присылает бот (block.widths,
 * block.notes) — так их можно менять без повторной вставки этого скрипта.
 * Пустые «Активные» у старых дней — не ошибка: Firebase не хранит историю
 * входов, только последний.
 */
function renderAppStats(spreadsheet, block) {
  if (!block || !block.header) {
    return;
  }

  const sheet = prepareSheet(spreadsheet, APP_STATS_SHEET, '#2a78d6');
  const rows = block.rows || [];
  const width = block.header.length;
  const lastRow = drawTable(sheet, block.header, rows, 1, {
    countColumns: [2, 3, 5, 7, 8, 9],
    percentColumns: [4, 6],
  });

  // Заголовки в две строки: переносим и даём шапке высоту.
  sheet.getRange(1, 1, 1, width).setWrap(true).setVerticalAlignment('middle');
  sheet.setRowHeight(1, 46);

  const widths = block.widths || APP_STATS_WIDTHS;
  widths.forEach(function (px, index) {
    if (index < width) {
      sheet.setColumnWidth(index + 1, px);
    }
  });

  // Подсказка при наведении на заголовок: как считается цифра.
  (block.notes || []).forEach(function (note, index) {
    if (index < width && note) {
      sheet.getRange(1, index + 1).setNote(note);
    }
  });

  if (rows.length === 0) {
    return;
  }

  sheet.getRange(2, 1, lastRow - 1, 1).setFontColor(INK);
  sheet.getRange(2, 5, lastRow - 1, 1).setFontColor(INK).setFontWeight('bold');
  sheet.getRange(2, 9, lastRow - 1, 1).setFontColor(INK_MUTED);

  drawBorders(sheet, 1, lastRow, width);
  sheet.getRange(lastRow, 1, 1, width).setBackground('#f1f3f4');
}
