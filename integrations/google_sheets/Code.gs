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
const COUNT_FORMAT = '0';

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
  sheet.setHiddenGridlines(true);
  sheet.setTabColor(tabColor);
  return sheet;
}
