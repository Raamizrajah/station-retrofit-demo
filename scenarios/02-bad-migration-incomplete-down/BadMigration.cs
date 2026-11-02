using System;
using Microsoft.EntityFrameworkCore.Migrations;

namespace StationRetrofit.Database.Migrations;

/// <summary>
/// BAD: Down() only reverses 1 of 4 operations from Up().
/// </summary>
public partial class AddProductAuditFields : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.AddColumn<string>(
            name: "category",
            table: "products",
            type: "character varying(100)",
            maxLength: 100,
            nullable: true);

        migrationBuilder.AddColumn<string>(
            name: "updated_by",
            table: "products",
            type: "character varying(200)",
            maxLength: 200,
            nullable: true);

        migrationBuilder.AddColumn<DateTime>(
            name: "updated_at",
            table: "products",
            type: "timestamp with time zone",
            nullable: true);

        migrationBuilder.CreateIndex(
            name: "ix_products_category",
            table: "products",
            column: "category");
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        // BUG: Only removes 1 of 3 columns, doesn't drop the index.
        // Missing: DropColumn("category"), DropColumn("updated_by"), DropIndex("ix_products_category")
        migrationBuilder.DropColumn(
            name: "updated_at",
            table: "products");
    }
}
