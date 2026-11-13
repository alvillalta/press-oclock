export const randomEmail = () =>
  `test_${Math.random().toString(36).substring(7)}@example.com`

export const randomPassword = () => `${Math.random().toString(36).substring(2)}`
