// Unified password policy — must match backend security_middleware.py
// Requirement: minimum 8 characters, at least one letter and one digit.
// A SINGLE message is shown to the user regardless of which rule fails.

export const isPasswordStrong = (pw) => {
  if (!pw || pw.length < 8) return false;
  if (!/[A-Za-zА-Яа-я]/.test(pw)) return false;
  if (!/\d/.test(pw)) return false;
  return true;
};

export const PASSWORD_REQUIREMENTS_MSG = {
  en: 'Password must be at least 8 characters and include letters and digits',
  ru: 'Пароль должен содержать минимум 8 символов, включая буквы и цифры',
  es: 'La contraseña debe tener al menos 8 caracteres e incluir letras y dígitos',
  zh: '密码至少需要8个字符，并包含字母和数字',
  fr: 'Le mot de passe doit comporter au moins 8 caractères et inclure des lettres et des chiffres',
  de: 'Das Passwort muss mindestens 8 Zeichen lang sein und Buchstaben und Ziffern enthalten',
  ja: 'パスワードは8文字以上で、英字と数字を含める必要があります',
  ko: '비밀번호는 8자 이상이며 문자와 숫자를 포함해야 합니다',
};

export const passwordMsg = (lang) => PASSWORD_REQUIREMENTS_MSG[lang] || PASSWORD_REQUIREMENTS_MSG.en;
