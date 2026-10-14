/**
 * BotArba -> Google Таблицы.
 *
 * Принимает снимок базы от бота и перезаписывает два листа: «Операции»
 * и «Сводка по дням». Перезапись, а не добавление строк: расход могут
 * отменить, возврат уменьшает поступление, продажа с кассы Kaspi приходит
 * задним числом — при перезаписи таблица всегда в точности равна базе бота.
 *
 * Установка — см. README.md рядом с этим файлом.
 */

// ⚠️ ЗАМЕНИТЕ на свой пароль и впишите тот же самый в переменную
// SHEETS_TOKEN у бота. Любая длинная случайная строка.
const TOKEN = 'ЗАМЕНИТЕ_НА_СВОЙ_ПАРОЛЬ';

const OPERATIONS_SHEET = 'Операции';
const DAILY_SHEET = 'Сводка по дням';

// Колонки с деньгами (нумерация с 1) — им ставится денежный формат.
const MONEY_COLUMNS = {
  'Операции': [5],
  'Сводка по дням': [2, 3, 4, 5, 6],
};

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
    writeSheet(spreadsheet, OPERATIONS_SHEET, payload.operations);
    writeSheet(spreadsheet, DAILY_SHEET, payload.daily);
    stampGeneratedAt(spreadsheet, payload.generated_at);

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

function writeSheet(spreadsheet, name, block) {
  if (!block || !block.header) {
    return;
  }

  let sheet = spreadsheet.getSheetByName(name);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(name);
  }

  const header = block.header;
  const rows = block.rows || [];

  // Чистим только область данных, а не весь лист: так не слетают
  // закрепления, фильтры и ширина колонок, настроенные пользователем.
  sheet.clear({ contentsOnly: true });

  sheet.getRange(1, 1, 1, header.length).setValues([header]);
  sheet.getRange(1, 1, 1, header.length)
    .setFontWeight('bold')
    .setBackground('#f1f3f4');
  sheet.setFrozenRows(1);

  if (rows.length > 0) {
    // Строки могут быть разной длины, если бот обновится раньше скрипта —
    // добиваем до ширины заголовка, иначе setValues падает.
    const normalized = rows.map(function (row) {
      const copy = row.slice(0, header.length);
      while (copy.length < header.length) {
        copy.push('');
      }
      return copy;
    });

    sheet.getRange(2, 1, normalized.length, header.length).setValues(normalized);

    (MONEY_COLUMNS[name] || []).forEach(function (column) {
      sheet.getRange(2, column, normalized.length, 1).setNumberFormat('#,##0.##');
    });
  }

  sheet.autoResizeColumns(1, header.length);
}

function stampGeneratedAt(spreadsheet, generatedAt) {
  if (!generatedAt) {
    return;
  }
  // Отметка времени в закреплённой ячейке, чтобы было видно, свежие ли данные.
  const sheet = spreadsheet.getSheetByName(DAILY_SHEET);
  if (sheet) {
    const column = sheet.getLastColumn() + 2;
    sheet.getRange(1, column).setValue('Обновлено: ' + generatedAt);
  }
}
