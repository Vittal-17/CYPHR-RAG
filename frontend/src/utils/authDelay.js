export const withAuthDelay = async (asyncAction) => {
  const minDelay = new Promise((resolve) => {
    setTimeout(resolve, 4000);
  });
  try {
    const [result] = await Promise.all([asyncAction(), minDelay]);
    return result;
  } catch (error) {
    await minDelay;
    throw error;
  }
};
