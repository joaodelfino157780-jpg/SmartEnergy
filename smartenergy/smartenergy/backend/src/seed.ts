import { PrismaClient } from "@prisma/client";
const prisma = new PrismaClient();

// [nome, cômodo, kWh/dia base]
const devices: [string, string, number][] = [
  ["Ar-condicionado", "Quarto", 6.0], ["Chuveiro elétrico", "Banheiro", 4.5],
  ["Geladeira", "Cozinha", 1.4], ["Máquina de lavar", "Lavanderia", 1.1],
  ["TV", "Sala", 0.6], ["Computador", "Escritório", 1.0], ["Iluminação", "Casa", 0.9],
];

async function main() {
  await prisma.reading.deleteMany();
  await prisma.device.deleteMany();
  for (const [name, room, base] of devices) {
    const dev = await prisma.device.create({ data: { name, room } });
    const data = [];
    for (let i = 60; i >= 1; i--) {
      const day = new Date(); day.setUTCHours(0, 0, 0, 0); day.setUTCDate(day.getUTCDate() - i);
      const weekend = [0, 6].includes(day.getUTCDay());
      let kwh = base * (weekend ? 1.2 : 1) * (0.85 + Math.random() * 0.3);
      if (name === "Ar-condicionado" && i === 2) kwh *= 2.5; // anomalia de exemplo
      data.push({ deviceId: dev.id, day, kwh: +kwh.toFixed(2) });
    }
    await prisma.reading.createMany({ data });
  }
  console.log("Seed concluído.");
}
main().finally(() => prisma.$disconnect());
