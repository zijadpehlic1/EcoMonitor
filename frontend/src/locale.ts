export const APP_LOCALE = 'bs-BA'
export const APP_TIMEZONE = 'Europe/Sarajevo'

export function formatNumber(value: number, fractionDigits = 1): string {
  const options = {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }
  // Some embedded browsers ship incomplete ICU data and silently use English.
  if (new Intl.NumberFormat(APP_LOCALE).format(1.5).includes(',')) {
    return new Intl.NumberFormat(APP_LOCALE, options).format(value)
  }
  return new Intl.NumberFormat('en-US', options).formatToParts(value)
    .map(part => part.type === 'decimal' ? ',' : part.type === 'group' ? '.' : part.value).join('')
}

export function formatInteger(value: number): string {
  return formatNumber(value, 0)
}

export function formatDate(value: string | Date): string {
  const parts = dateParts(value)
  return `${parts.day}.${parts.month}.${parts.year}.`
}

export function formatDateTime(value: string | Date): string {
  const parts = dateParts(value)
  return `${parts.day}.${parts.month}.${parts.year}. ${parts.hour}:${parts.minute}`
}

function dateParts(value: string | Date) {
  return Object.fromEntries(new Intl.DateTimeFormat(APP_LOCALE, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    hourCycle: 'h23', timeZone: APP_TIMEZONE,
  }).formatToParts(new Date(value)).map(part => [part.type, part.value]))
}

