/** "1 transaction", "3 transactions" */
export const transactionCount = (n: number) => `${n} transaction${n === 1 ? '' : 's'}`
