using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

namespace StationRetrofit.Database.Migrations;

/// <summary>
/// BAD: Backfill SQL is not idempotent — running twice creates duplicate rows.
/// </summary>
public partial class CreatePriceAuditLog : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.CreateTable(
            name: "price_audit_log",
            columns: table => new
            {
                id = table.Column<int>(type: "integer", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                price_entry_id = table.Column<int>(type: "integer", nullable: false),
                product_id = table.Column<int>(type: "integer", nullable: false),
                old_amount = table.Column<decimal>(type: "numeric(18,2)", nullable: false),
                new_amount = table.Column<decimal>(type: "numeric(18,2)", nullable: false),
                changed_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                changed_by = table.Column<string>(type: "character varying(200)", maxLength: 200, nullable: true)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_price_audit_log", x => x.id);
            });

        migrationBuilder.CreateIndex(
            name: "IX_price_audit_log_product_id",
            table: "price_audit_log",
            column: "product_id");

        migrationBuilder.CreateIndex(
            name: "IX_price_audit_log_price_entry_id",
            table: "price_audit_log",
            column: "price_entry_id");

        // BUG: No WHERE NOT EXISTS or ON CONFLICT — not idempotent!
        // If migration is retried after partial failure, duplicates will be inserted.
        migrationBuilder.Sql(@"
            INSERT INTO price_audit_log (price_entry_id, product_id, old_amount, new_amount, changed_at)
            SELECT
                pe.id,
                pe.product_id,
                pe.amount,
                pe.amount,
                pe.created_at
            FROM price_entries pe;
        ");
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropTable(name: "price_audit_log");
    }
}
